"""RAG source-of-truth store + retrieval (the Brain's grounding layer).

A retrievable, citation-bearing store of grounded facts (TCAD/GIS records, comps,
valuation runs, photo findings, listing fields) the Critic (U6) checks every
customer-facing claim against. Every retrievable fact carries a STABLE
``source_id`` and a provenance ``kind`` so each claim can be cited.

* :mod:`schema`     — ``Fact`` / ``Evidence`` / provenance kinds (the contract).
* :mod:`embedder`   — ``Embedder`` protocol, deterministic ``FakeEmbedder``, and
  a network-free ``RealEmbedder`` hook.
* :mod:`store`      — ``SourceStore`` interface, ``InMemoryVectorStore`` (tests/
  local), ``PgVectorStore`` (prod, lazily-connecting / import-safe).
* :mod:`retriever`  — ``Retriever`` (top-k provenance-tagged evidence; EMPTY on
  no match) plus ingest adapters for Brain outputs.

Covers U5 (plan: enables R11).
"""
from __future__ import annotations

from .schema import Evidence, Fact, ProvenanceKind, PROVENANCE_KINDS
from .embedder import (
    DEFAULT_DIM,
    Embedder,
    FakeEmbedder,
    RealEmbedder,
    cosine_similarity,
)
from .store import (
    InMemoryVectorStore,
    PgVectorStore,
    SourceStore,
)
from .retriever import (
    DEFAULT_TOP_K,
    Retriever,
    listing_field_facts,
    photo_finding_facts,
    valuation_facts,
)

__all__ = [
    # schema
    "Fact",
    "Evidence",
    "ProvenanceKind",
    "PROVENANCE_KINDS",
    # embedder
    "Embedder",
    "FakeEmbedder",
    "RealEmbedder",
    "DEFAULT_DIM",
    "cosine_similarity",
    # store
    "SourceStore",
    "InMemoryVectorStore",
    "PgVectorStore",
    # retriever
    "Retriever",
    "DEFAULT_TOP_K",
    "valuation_facts",
    "photo_finding_facts",
    "listing_field_facts",
]
