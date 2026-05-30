"""The Critic: the fixed verification pipeline that gates every customer message.

This is U6, the load-bearing safety rail. It is a FIXED pipeline, separate from
any generator — it only verifies a *given* draft, it never writes one:

    decompose -> (per claim) retrieve evidence -> entail -> cite -> score
              -> block / escalate

Rules (the trust contract):

* ``decompose`` splits the draft into atomic claims.
* For each claim the injected RAG :class:`~brain.rag.Retriever` fetches
  provenance-tagged evidence. A claim with NO retrieved source is ``BASELESS``
  ("no source -> no claim").
* The injected :class:`~brain.lawyer.entailment.Entailer` labels each claim
  ``ENTAILED`` / ``CONTRADICTED`` / ``BASELESS``. An ``ENTAILED`` claim binds a
  citation (the evidence ``source_id``).
* Any ``CONTRADICTED`` or ``BASELESS`` claim — or a composite confidence below
  ``threshold`` — BLOCKS the message (``approved=False``) and sets
  ``escalate=True``. A ``CONTRADICTED`` claim always escalates.
* "No source -> no claim": unsupported claims are stripped from a rebuilt
  ``approved_message`` (and the whole draft escalates) rather than ever sent.

The result is a structured :class:`VerificationResult` carrying per-claim
verdicts and citations — shaped to be written to the Rails audit table later
(U9). This module does NOT touch any database; it returns the record.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from brain.rag import Retriever

from .decompose import Claim, decompose
from .entailment import Entailer, Label

# Default composite-confidence floor. A draft whose mean entailment score falls
# below this blocks + escalates even if no single claim is contradicted/baseless.
DEFAULT_THRESHOLD: float = 0.6

# Default per-query evidence breadth (mirrors rag.DEFAULT_TOP_K intent; kept
# local so the Critic owns its retrieval budget).
DEFAULT_TOP_K: int = 5


@dataclass(frozen=True)
class ClaimVerdict:
    """The Critic's decision about one atomic claim — a loggable audit row.

    Carries the claim text and its original ``index``, the entailment
    ``label``/``score``, the bound ``citation`` (source id, present iff
    ``ENTAILED``), the ``kind`` of that source, and a human-readable ``reason``.
    ``supported`` is the send-gate for this single claim.
    """

    index: int
    claim: str
    label: Label
    score: float
    citation: Optional[str] = None
    source_kind: Optional[str] = None
    reason: str = ""

    @property
    def supported(self) -> bool:
        """True iff this claim is entailed AND bound to a citation (sendable)."""
        return self.label is Label.ENTAILED and self.citation is not None


@dataclass(frozen=True)
class VerificationResult:
    """Structured outcome of verifying a draft — the unit logged to the audit store.

    ``approved`` — the message is safe to send as-is (every claim supported).
    ``escalate`` — route to a human (any contradicted/baseless claim or a
    sub-threshold composite score). ``confidence`` — composite faithfulness in
    ``[0, 1]``. ``reason`` — why the draft was approved or blocked.
    ``claims`` — per-claim verdicts + citations (the claim->source decisions).
    ``approved_message`` — the draft rebuilt from only the supported claims
    (unsupported claims stripped); ``None`` when nothing survives.
    """

    approved: bool
    escalate: bool
    confidence: float
    reason: str
    claims: List[ClaimVerdict] = field(default_factory=list)
    approved_message: Optional[str] = None

    @property
    def citations(self) -> List[str]:
        """Distinct source ids cited by the supported claims, in order."""
        seen: list[str] = []
        for v in self.claims:
            if v.supported and v.citation is not None and v.citation not in seen:
                seen.append(v.citation)
        return seen

    def audit_rows(self) -> List[dict]:
        """Flatten per-claim decisions into plain dicts for the U9 audit table.

        One row per claim — claim text, verdict, score, bound source id/kind,
        whether it was sent — ready to persist without importing the DB here.
        """
        return [
            {
                "index": v.index,
                "claim": v.claim,
                "label": v.label.value,
                "score": v.score,
                "citation": v.citation,
                "source_kind": v.source_kind,
                "supported": v.supported,
                "reason": v.reason,
            }
            for v in self.claims
        ]


@dataclass
class Critic:
    """The fixed decompose -> retrieve -> entail -> cite -> score -> gate pipeline.

    ``retriever`` and ``entailer`` are injected (dependency injection), so the
    same Critic runs over the in-memory RAG store + ``FakeEntailer`` in tests or
    a pgvector store + real LLM entailer in prod. ``threshold`` is the composite
    confidence floor; ``top_k`` the per-claim evidence budget.

    The Critic is SEPARATE from any generator: :meth:`verify` takes a finished
    draft and only inspects it.
    """

    retriever: Retriever
    entailer: Entailer
    threshold: float = DEFAULT_THRESHOLD
    top_k: int = DEFAULT_TOP_K

    def verify(self, draft: str, *, address: Optional[str] = None) -> VerificationResult:
        """Verify ``draft`` against source data; return a structured verdict.

        ``address`` optionally scopes retrieval to a property. Every claim is
        decomposed, grounded against retrieved evidence, entailed, and (if
        entailed) cited. The send-gate and escalation follow the trust contract
        documented at module level.
        """
        claims: List[Claim] = decompose(draft)

        # An empty/blank draft makes no claims: nothing to send, nothing to
        # escalate. Treat as approved-but-empty rather than a safety trip.
        if not claims:
            return VerificationResult(
                approved=True,
                escalate=False,
                confidence=1.0,
                reason="empty draft: no claims to verify",
                claims=[],
                approved_message=None,
            )

        verdicts: List[ClaimVerdict] = []
        for claim in claims:
            evidence = self.retriever.retrieve(
                claim.text, address=address, top_k=self.top_k
            )
            verdict = self.entailer.entail(claim.text, evidence)

            if verdict.is_entailed and verdict.source_id is not None:
                citation = verdict.source_id
                source_kind = verdict.evidence.kind if verdict.evidence else None
            else:
                citation = None
                source_kind = None

            verdicts.append(
                ClaimVerdict(
                    index=claim.index,
                    claim=claim.text,
                    label=verdict.label,
                    score=verdict.score,
                    citation=citation,
                    source_kind=source_kind,
                    reason=verdict.rationale,
                )
            )

        return self._gate(verdicts)

    def _gate(self, verdicts: List[ClaimVerdict]) -> VerificationResult:
        """Apply the block/escalate rules and rebuild the approved message."""
        contradicted = [v for v in verdicts if v.label is Label.CONTRADICTED]
        baseless = [v for v in verdicts if v.label is Label.BASELESS]
        supported = [v for v in verdicts if v.supported]

        # Composite confidence: mean entailment score across all claims. A draft
        # with any unsupported claim is dragged down (their score is 0.0).
        confidence = round(sum(v.score for v in verdicts) / len(verdicts), 4)

        # Rebuild the message from only the supported (cited) claims.
        approved_message = (
            ". ".join(v.claim.rstrip(".") for v in supported) + "."
            if supported
            else None
        )

        all_supported = len(supported) == len(verdicts)
        below_threshold = confidence < self.threshold

        if contradicted:
            return VerificationResult(
                approved=False,
                escalate=True,
                confidence=confidence,
                reason=(
                    f"{len(contradicted)} contradicted claim(s) against source "
                    f"data — blocked and escalated to human review"
                ),
                claims=verdicts,
                approved_message=approved_message,
            )

        if baseless:
            return VerificationResult(
                approved=False,
                escalate=True,
                confidence=confidence,
                reason=(
                    f"{len(baseless)} unsupported claim(s) with no source "
                    f"(no source -> no claim) — stripped; draft escalated"
                ),
                claims=verdicts,
                approved_message=approved_message,
            )

        if below_threshold:
            return VerificationResult(
                approved=False,
                escalate=True,
                confidence=confidence,
                reason=(
                    f"composite confidence {confidence:.2f} below threshold "
                    f"{self.threshold:.2f} — escalated"
                ),
                claims=verdicts,
                approved_message=approved_message,
            )

        # Every claim entailed + cited and the composite clears the bar.
        return VerificationResult(
            approved=all_supported,
            escalate=not all_supported,
            confidence=confidence,
            reason="all claims entailed by source data and cited",
            claims=verdicts,
            approved_message=approved_message,
        )

    __call__ = verify
