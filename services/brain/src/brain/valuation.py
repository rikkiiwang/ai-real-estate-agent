"""Valuation core (the "Brain").

U1 ships a deterministic placeholder so the cross-language gRPC round-trip is
testable. U3 replaces ``estimate_value`` with the gradient-boosting AVM over
TCAD + GIS + synthetic-listing features, and returns real source-backed facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Fact:
    source_id: str
    kind: str
    description: str
    contribution: float = 0.0


@dataclass
class Valuation:
    sufficient_data: bool
    estimate: float = 0.0
    low: float = 0.0
    high: float = 0.0
    facts: list[Fact] = field(default_factory=list)


# Addresses with no ingested coverage return insufficient_data rather than a
# fabricated number (R1/R3 honesty; see U3 verification).
_KNOWN_COVERAGE: set[str] = set()


def estimate_value(address: str) -> Valuation:
    """Return a source-cited valuation for ``address``.

    Placeholder implementation: any non-empty address is treated as covered and
    valued deterministically from the address string so tests are stable. Real
    coverage + AVM arrive in U3; the insufficient-data contract is already wired.
    """
    address = (address or "").strip()
    if not address:
        return Valuation(sufficient_data=False)

    # Deterministic stand-in for the AVM (U3 replaces this).
    base = 250_000 + (sum(ord(c) for c in address) % 500) * 1_000
    return Valuation(
        sufficient_data=True,
        estimate=float(base),
        low=float(base) * 0.95,
        high=float(base) * 1.05,
        facts=[
            Fact(
                source_id=f"placeholder:{address}",
                kind="placeholder",
                description="U1 placeholder valuation; replaced by the AVM in U3.",
                contribution=float(base),
            )
        ],
    )
