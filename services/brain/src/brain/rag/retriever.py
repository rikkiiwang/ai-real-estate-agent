"""Retriever: the read side of the source-of-truth store.

Given a claim's text and an optional address scope, the :class:`Retriever`
embeds the query and returns the top-k provenance-tagged
:class:`~brain.rag.schema.Evidence` — each carrying a stable ``source_id`` and
``kind`` the Critic (U6) cites.

CRITICAL CONTRACT: a query that matches no stored source returns an EMPTY list.
This is what drives the Critic's "no source -> no claim" rule, so the retriever
never fabricates or pads results. An optional ``min_score`` floor lets callers
treat weak, effectively-unrelated matches as no match.

Ingest helpers (``ingest_valuation``, ``ingest_photo_findings``,
``ingest_listing_fields``) turn the Brain's existing outputs (valuation runs,
photo findings, listing records) into provenance-tagged facts without those
modules depending on RAG.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from .embedder import Embedder
from .schema import Evidence, Fact
from .store import SourceStore

# Default number of evidence items returned per query.
DEFAULT_TOP_K: int = 5


@dataclass
class Retriever:
    """Embed a query and fetch the top-k provenance-tagged evidence.

    ``store`` and ``embedder`` are injected so the same retriever works over the
    in-memory store (tests) or pgvector (prod). ``min_score`` is an optional
    similarity floor below which a candidate is treated as no match — keeping the
    empty-on-no-source contract meaningful even when the store would otherwise
    return a weakly-related row.
    """

    store: SourceStore
    embedder: Embedder
    min_score: float = 0.0

    def ingest(self, fact: Fact) -> None:
        """Add one provenance-bearing fact to the underlying store."""
        self.store.ingest(fact)

    def ingest_many(self, facts: Iterable[Fact]) -> None:
        """Add many provenance-bearing facts to the underlying store."""
        self.store.ingest_many(list(facts))

    def retrieve(
        self,
        claim: str,
        *,
        address: Optional[str] = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> List[Evidence]:
        """Return up to ``top_k`` evidence for ``claim``, or ``[]`` if none.

        ``address`` narrows the search to facts scoped to that address. The
        result is ordered by descending similarity; evidence scoring below
        ``min_score`` is dropped, so a query with no real match returns an empty
        list (the "no source -> no claim" contract).
        """
        if not claim or not claim.strip():
            return []
        query_embedding = self.embedder.embed(claim)
        evidence = self.store.search(query_embedding, top_k=top_k, address=address)
        return [e for e in evidence if e.score >= self.min_score]

    def has_support(
        self,
        claim: str,
        *,
        address: Optional[str] = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> bool:
        """True iff at least one source backs the claim (drives no-claim rule)."""
        return bool(self.retrieve(claim, address=address, top_k=top_k))


# --- ingest adapters: Brain outputs -> provenance-tagged facts ---------------
#
# These keep valuation/vision/ingestion modules free of any RAG dependency: the
# orchestrator (U10) calls these to push their outputs into the store as facts.


def valuation_facts(
    address: str,
    valuation: object,
    *,
    run_id: str,
) -> List[Fact]:
    """Convert a valuation result into provenance-tagged facts.

    Accepts a duck-typed valuation (the U3 ``Valuation``: ``sufficient_data``,
    ``estimate``, ``low``, ``high``, ``facts`` with ``description``/``source_id``)
    without importing the valuation package. The point estimate becomes a
    ``valuation_run`` fact; each feature contribution becomes its own fact tying
    the cited number to the run. An insufficient-data valuation yields NO facts
    (nothing grounded to retrieve).
    """
    if not getattr(valuation, "sufficient_data", False):
        return []
    facts: List[Fact] = [
        Fact(
            source_id=f"{run_id}:estimate",
            kind="valuation_run",
            content=(
                f"Estimated value for {address} is ${valuation.estimate:,.0f} "
                f"(range ${valuation.low:,.0f}-${valuation.high:,.0f})."
            ),
            address=address,
            metadata={"run_id": run_id, "estimate": float(valuation.estimate)},
        )
    ]
    for i, vfact in enumerate(getattr(valuation, "facts", []) or []):
        facts.append(
            Fact(
                source_id=f"{run_id}:feature:{i}",
                kind="valuation_run",
                content=(
                    f"{getattr(vfact, 'description', 'feature')} contributes "
                    f"${getattr(vfact, 'contribution', 0.0):,.0f} to the {address} valuation."
                ),
                address=address,
                metadata={
                    "run_id": run_id,
                    "backing_source_id": getattr(vfact, "source_id", None),
                    "feature_kind": getattr(vfact, "kind", None),
                },
            )
        )
    return facts


def photo_finding_facts(address: str, findings: Iterable[object]) -> List[Fact]:
    """Convert vision findings into ``photo_finding`` facts.

    Accepts duck-typed findings (the U4 ``Finding``: ``label``, ``confidence``,
    ``evidence_photo_id``, ``kind``) without importing the vision package. Each
    finding is cited to its source photo via ``evidence_photo_id``.
    """
    facts: List[Fact] = []
    for finding in findings:
        photo_id = getattr(finding, "evidence_photo_id", None)
        label = getattr(finding, "label", "finding")
        if not photo_id:
            continue
        facts.append(
            Fact(
                source_id=f"photo:{photo_id}:{label}",
                kind="photo_finding",
                content=(
                    f"Photo {photo_id} shows {label} "
                    f"(confidence {getattr(finding, 'confidence', 0.0):.2f})."
                ),
                address=address,
                metadata={
                    "photo_id": photo_id,
                    "label": label,
                    "finding_kind": getattr(finding, "kind", None),
                },
            )
        )
    return facts


def listing_field_facts(
    address: str,
    fields: dict,
    *,
    listing_id: str,
) -> List[Fact]:
    """Convert listing fields into ``listing_field`` facts, one per field.

    Each field gets a stable per-field ``source_id`` so a refreshed listing
    upserts cleanly rather than duplicating evidence.
    """
    facts: List[Fact] = []
    for name, value in fields.items():
        facts.append(
            Fact(
                source_id=f"listing:{listing_id}:{name}",
                kind="listing_field",
                content=f"{address} listing reports {name} = {value}.",
                address=address,
                metadata={"listing_id": listing_id, "field": name},
            )
        )
    return facts
