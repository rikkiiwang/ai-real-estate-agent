"""RAG source-of-truth data shapes: facts, evidence, provenance.

Every retrievable unit in the store is a :class:`Fact`: a human-readable piece
of grounded content carrying a STABLE ``source_id`` and a ``kind`` (its
provenance). Retrieval returns :class:`Evidence` — a fact plus its similarity
score — so the Critic (U6) can bind each claim to a cited source and enforce its
"no source -> no claim" rule. Nothing retrievable exists without provenance.

These dataclasses are the stable contract the retriever and both store
implementations speak; their field shapes must not change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, get_args

# The provenance kinds a fact may carry. Mirrors the source systems the Brain
# grounds against (TCAD appraisal, GIS attribute, listing field, comp sale,
# valuation run, photo finding). The Critic cites by (source_id, kind).
ProvenanceKind = Literal[
    "tcad_appraisal",
    "gis_attribute",
    "listing_field",
    "comp_sale",
    "valuation_run",
    "photo_finding",
]

# Tuple of the valid kinds, derived from the Literal so the two never drift.
PROVENANCE_KINDS: tuple[str, ...] = get_args(ProvenanceKind)


@dataclass(frozen=True)
class Fact:
    """One grounded, citable fact held in the source-of-truth store.

    ``source_id`` is a STABLE identifier for the source record this fact came
    from (e.g. a TCAD account number, a GIS attribute id, a valuation run id);
    re-ingesting the same source replaces the prior fact rather than duplicating
    it. ``kind`` is the provenance class. ``content`` is the human-readable
    statement the Critic checks a claim against. ``address`` is the optional
    address scope a query can be narrowed to (``None`` = not address-scoped).
    ``metadata`` carries any extra structured provenance (account number, run
    id, photo id) without changing the contract.
    """

    source_id: str
    kind: ProvenanceKind
    content: str
    address: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id or not self.source_id.strip():
            raise ValueError("fact must carry a non-empty stable source_id")
        if self.kind not in PROVENANCE_KINDS:
            raise ValueError(f"invalid provenance kind: {self.kind!r}")
        if not self.content or not self.content.strip():
            raise ValueError("fact must carry non-empty content")


@dataclass(frozen=True)
class Evidence:
    """A retrieved fact plus the similarity score that surfaced it.

    The retriever returns these ordered by descending ``score``; the Critic uses
    ``fact.source_id`` / ``fact.kind`` to cite and ``score`` to gauge retrieval
    coverage. An empty list of these is the "no source" signal (no claim).
    """

    fact: Fact
    score: float

    @property
    def source_id(self) -> str:
        """Convenience accessor for the cited source id."""
        return self.fact.source_id

    @property
    def kind(self) -> str:
        """Convenience accessor for the cited provenance kind."""
        return self.fact.kind
