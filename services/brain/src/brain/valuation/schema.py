"""Valuation data shapes.

The public dataclasses ``Fact`` and ``Valuation`` are the stable contract the
gRPC server (``brain.server``) maps onto the proto ``GetValuationResponse`` —
their field shapes must not change. ``PropertyRecord`` is the normalized input
the feature module derives a feature vector from; in U2/U5 it is filled from the
real TCAD/GIS/listing join, here it is derived deterministically per address.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Fact:
    """A source-cited contributor to a valuation.

    ``contribution`` is the model-attributed dollar effect of the feature this
    fact describes, so the Critic (U6) can bind each cited number to a source.
    """

    source_id: str
    kind: str
    description: str
    contribution: float = 0.0


@dataclass
class Valuation:
    """A valuation result: point estimate, uncertainty band, and source facts.

    ``sufficient_data=False`` means the address has no ingested coverage; the
    estimate/band are left at zero rather than fabricated (R1 honesty).
    """

    sufficient_data: bool
    estimate: float = 0.0
    low: float = 0.0
    high: float = 0.0
    facts: list[Fact] = field(default_factory=list)


@dataclass(frozen=True)
class PropertyRecord:
    """A normalized property record — the AVM's input before featurization.

    Mirrors the value-bearing TCAD/GIS/listing fields the real ingestion join
    (U2/U5) will supply. ``condition`` is the optional photo-derived condition
    score in ``[0, 1]`` (U4's vision output is the source; it is passed in, never
    imported here). ``None`` means "no photo signal", handled as a sparse input.
    """

    address: str
    beds: float
    baths: float
    sqft: float
    lot_sqft: float
    year_built: int
    latitude: float
    longitude: float
    garage_spaces: float = 0.0
    condition: Optional[float] = None
    # Provenance: source record ids backing this record's fields, for citation.
    source_ids: tuple[str, ...] = ()
