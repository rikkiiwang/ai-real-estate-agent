"""Entailment labeling: does the retrieved evidence support a claim?

The Critic (U6) checks each atomic claim against the source evidence the RAG
retriever surfaced. That check is an :class:`Entailer`: given a ``(claim,
evidence)`` pair it returns a :class:`Verdict` — one of ``ENTAILED`` (the source
supports the claim), ``CONTRADICTED`` (the source asserts the opposite), or
``BASELESS`` (no source bears on the claim) — plus a ``score`` in ``[0, 1]``
expressing how strongly the evidence entails the claim. This is the load-bearing
safety contract: a claim is only allowed to reach a customer if it is
``ENTAILED`` and bound to a citation.

* :class:`FakeEntailer` — deterministic, network-free. Labels by token overlap
  between claim and evidence, with explicit negation detection so a flatly
  contradicting source is caught, and an optional fixtures map for tests that
  want to pin a specific verdict. Used everywhere in the test suite.
* :class:`RealEntailer` — a thin hook around an injected LLM / NLI client
  (RAGAS-faithfulness style: decompose-already-done, then ask the model whether
  each claim is supported by the retrieved context). It BUILDS the request and
  delegates; with no client injected it refuses to run rather than reaching the
  network, mirroring ``RealEmbedder`` / ``GeminiVisionModel`` discipline.

No heavy dependencies (no ``ragas``): the protocol is abstracted so a real
backend slots in later without touching the Critic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional, Protocol, Sequence, runtime_checkable

from brain.rag import Evidence


class Label(str, Enum):
    """The three entailment outcomes for a (claim, evidence) pair.

    ``ENTAILED`` — the evidence supports the claim (citable, sendable).
    ``CONTRADICTED`` — the evidence asserts the opposite (blocks + escalates).
    ``BASELESS`` — no evidence bears on the claim ("no source -> no claim").
    """

    ENTAILED = "ENTAILED"
    CONTRADICTED = "CONTRADICTED"
    BASELESS = "BASELESS"


@dataclass(frozen=True)
class Verdict:
    """An entailment label plus its strength and the evidence it rested on.

    ``score`` is the faithfulness strength in ``[0, 1]``: how strongly the
    chosen ``evidence`` entails the claim (0.0 when ``BASELESS``). ``evidence``
    is the single best-supporting evidence item (``None`` when baseless), from
    which the Critic reads ``source_id`` to bind a citation. ``rationale`` is a
    short human-readable reason, suitable for the audit log.
    """

    label: Label
    score: float
    evidence: Optional[Evidence] = None
    rationale: str = ""

    @property
    def is_entailed(self) -> bool:
        return self.label is Label.ENTAILED

    @property
    def source_id(self) -> Optional[str]:
        """The citable source id when entailed, else ``None``."""
        return self.evidence.source_id if self.evidence is not None else None


@runtime_checkable
class Entailer(Protocol):
    """Labels whether retrieved evidence entails a claim.

    Implementations must return a :class:`Verdict`. Given an EMPTY evidence list
    the verdict MUST be ``BASELESS`` with score ``0.0`` — that is the "no source
    -> no claim" contract, and the Critic relies on it.
    """

    def entail(self, claim: str, evidence: Sequence[Evidence]) -> Verdict:
        ...


# --- deterministic test double -----------------------------------------------

# Tokens that flip the polarity of a statement. Used by the FakeEntailer to tell
# a supporting source ("has a pool") from a contradicting one ("no pool").
_NEGATIONS = frozenset({"no", "not", "never", "without", "lacks", "lacking", "n't"})

# Low-signal words ignored when measuring claim/evidence token overlap so the
# overlap reflects substantive terms, not glue words.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "this", "that", "these", "those", "it", "its", "of", "to", "in", "on",
        "at", "for", "and", "or", "with", "has", "have", "had", "as", "by",
        "from", "property", "home", "house", "listing",
    }
)


def _tokenize(text: str) -> List[str]:
    """Lowercase word tokens, punctuation stripped (apostrophes kept for n't)."""
    cleaned = []
    for raw in text.lower().split():
        token = raw.strip(".,!?;:()[]\"'")
        if token:
            cleaned.append(token)
    return cleaned


def _content_tokens(tokens: Sequence[str]) -> set[str]:
    """Substantive tokens (stopwords + negations removed) for overlap scoring."""
    return {t for t in tokens if t not in _STOPWORDS and t not in _NEGATIONS}


def _has_negation(tokens: Sequence[str]) -> bool:
    return any(t in _NEGATIONS for t in tokens)


@dataclass
class FakeEntailer:
    """Deterministic, network-free entailer for hermetic tests + local dev.

    The verdict for a ``(claim, evidence)`` pair is computed as:

    * EMPTY evidence -> ``BASELESS`` (score 0.0). The hard contract.
    * An explicit ``fixtures`` entry for the (normalized) claim text -> that
      pinned label (lets a test assert a CONTRADICTED path without crafting
      negation text).
    * Otherwise label by substantive token overlap between the claim and the
      best-overlapping evidence: high overlap -> ``ENTAILED`` (score = overlap
      fraction); high overlap but MISMATCHED negation polarity (the source says
      the opposite) -> ``CONTRADICTED``; little/no overlap -> ``BASELESS``.

    Pure function of its inputs: no randomness, no I/O.
    """

    # Minimum substantive-token overlap fraction to consider the claim grounded.
    entail_threshold: float = 0.5
    # claim text (normalized) -> forced label, for tests that pin a verdict.
    fixtures: dict[str, Label] = field(default_factory=dict)

    @staticmethod
    def _norm(claim: str) -> str:
        return " ".join(claim.lower().split())

    def entail(self, claim: str, evidence: Sequence[Evidence]) -> Verdict:
        if not evidence:
            return Verdict(
                label=Label.BASELESS,
                score=0.0,
                evidence=None,
                rationale="no source retrieved for claim (no source -> no claim)",
            )

        forced = self.fixtures.get(self._norm(claim))

        claim_tokens = _tokenize(claim)
        claim_content = _content_tokens(claim_tokens)
        claim_negated = _has_negation(claim_tokens)

        # Pick the evidence with the strongest substantive overlap.
        best: Optional[Evidence] = None
        best_overlap = 0.0
        best_polarity_mismatch = False
        for ev in evidence:
            ev_tokens = _tokenize(ev.fact.content)
            ev_content = _content_tokens(ev_tokens)
            if not claim_content:
                overlap = 0.0
            else:
                overlap = len(claim_content & ev_content) / len(claim_content)
            if best is None or overlap > best_overlap:
                best = ev
                best_overlap = overlap
                best_polarity_mismatch = _has_negation(ev_tokens) != claim_negated

        assert best is not None  # evidence is non-empty

        if forced is not None:
            return Verdict(
                label=forced,
                score=1.0 if forced is Label.ENTAILED else 0.0,
                evidence=best if forced is Label.ENTAILED else best,
                rationale=f"pinned fixture verdict {forced.value}",
            )

        if best_overlap >= self.entail_threshold:
            if best_polarity_mismatch:
                return Verdict(
                    label=Label.CONTRADICTED,
                    score=0.0,
                    evidence=best,
                    rationale=(
                        f"source overlaps the claim but with opposite polarity "
                        f"(overlap {best_overlap:.2f})"
                    ),
                )
            return Verdict(
                label=Label.ENTAILED,
                score=round(best_overlap, 4),
                evidence=best,
                rationale=f"source supports claim (overlap {best_overlap:.2f})",
            )

        return Verdict(
            label=Label.BASELESS,
            score=0.0,
            evidence=None,
            rationale=(
                f"retrieved source does not bear on the claim "
                f"(overlap {best_overlap:.2f} < {self.entail_threshold})"
            ),
        )


# --- real backend hook (no network on its own) -------------------------------

# Default RAGAS-faithfulness-style instruction: judge each claim against the
# retrieved context and return a label + a 0..1 support score.
_REAL_ENTAILER_SYSTEM = (
    "You are a faithfulness verifier for a real-estate assistant. Given a single "
    "atomic CLAIM and the retrieved SOURCE CONTEXT, decide whether the context "
    "ENTAILS the claim, CONTRADICTS it, or is BASELESS (does not bear on it). "
    "Reply with the label and a support score in [0,1]. Never use outside "
    "knowledge; judge only against the provided context."
)


@dataclass
class RealEntailer:
    """Thin hook around an injected LLM / NLI client — never networks on its own.

    A later unit wires a real client (the callable that, given a request dict,
    returns ``{"label": ..., "score": ...}``). With no client injected,
    :meth:`entail` refuses to run rather than reaching out — mirroring
    ``RealEmbedder``. :meth:`build_request` exposes the RAGAS-faithfulness-style
    payload for inspection/testing without sending it.

    Kept dependency-light on purpose: no ``ragas`` import. The faithfulness
    contract (decompose-then-judge-each-claim-against-context) is encoded in the
    request the client receives, so a RAGAS or raw-LLM backend can fulfill it.
    """

    client: Optional[Callable[[dict], dict]] = None
    model_name: str = "gpt-4o-mini"
    system_prompt: str = _REAL_ENTAILER_SYSTEM

    def build_request(self, claim: str, evidence: Sequence[Evidence]) -> dict:
        """Construct the faithfulness-judgement request payload (does not send)."""
        return {
            "model": self.model_name,
            "system": self.system_prompt,
            "claim": claim,
            "context": [
                {"source_id": ev.source_id, "kind": ev.kind, "content": ev.fact.content}
                for ev in evidence
            ],
        }

    def entail(self, claim: str, evidence: Sequence[Evidence]) -> Verdict:
        if not evidence:
            # Honor the hard contract without spending a model call.
            return Verdict(
                label=Label.BASELESS,
                score=0.0,
                evidence=None,
                rationale="no source retrieved for claim (no source -> no claim)",
            )
        if self.client is None:
            raise RuntimeError(
                "RealEntailer has no entailment client injected; provide one to "
                "run, or use FakeEntailer in tests."
            )
        response = self.client(self.build_request(claim, evidence))
        label = Label(str(response["label"]).upper())
        score = float(response.get("score", 0.0))
        chosen = evidence[0] if label is Label.ENTAILED else None
        return Verdict(
            label=label,
            score=score,
            evidence=chosen,
            rationale=str(response.get("rationale", "")),
        )
