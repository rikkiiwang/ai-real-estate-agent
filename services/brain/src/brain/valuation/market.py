# services/brain/src/brain/valuation/market.py
"""Market grounding for the AVM: anchor the estimate on real comps.

Given the model's prediction and a set of REAL comparable ACTIVE listings, this
computes a recency-weighted comp price-per-sqft anchor and blends it with the
model (comps dominant), so the final number reflects the live local market while
the model still contributes structure and the explainable per-feature drivers.
Comps are active listings (asking prices) and are labeled as such — never sales.
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import Prediction
from .schema import CompInput, Fact

# Weight of the comp anchor in the blend (comps dominate; model adds structure).
COMP_ANCHOR_ALPHA: float = 0.7
# Half-life (days) for recency weighting a comp's influence.
COMP_HALFLIFE_DAYS: float = 30.0


@dataclass
class MarketResult:
    estimate: float
    low: float
    high: float
    facts: list[Fact]


def _recency_weight(age_days: int) -> float:
    return 0.5 ** (max(0, age_days) / COMP_HALFLIFE_DAYS)


def anchor_and_blend(
    prediction: Prediction,
    *,
    subject_sqft: float,
    comps: list[CompInput],
) -> MarketResult:
    """Blend the model prediction with a recency-weighted comp anchor."""
    usable = [c for c in comps if c.sqft > 0 and c.price > 0]
    if not usable or subject_sqft <= 0:
        return MarketResult(
            estimate=prediction.estimate, low=prediction.low,
            high=prediction.high, facts=[],
        )

    weights = [_recency_weight(c.age_days) for c in usable]
    wsum = sum(weights) or 1.0
    anchor_ppsf = sum(w * c.price_per_sqft for w, c in zip(weights, usable)) / wsum
    comp_anchor = anchor_ppsf * subject_sqft

    estimate = COMP_ANCHOR_ALPHA * comp_anchor + (1.0 - COMP_ANCHOR_ALPHA) * prediction.estimate

    # Band: union the model band with the comp dispersion (implied subject prices).
    implied = sorted(c.price_per_sqft * subject_sqft for c in usable)
    low = min(prediction.low, implied[0], estimate)
    high = max(prediction.high, implied[-1], estimate)
    low = max(0.0, low)

    facts = [
        Fact(
            source_id=f"comp:{c.id}",
            kind="comp:active_listing",
            description=(
                f"Active listing {c.address}: ${c.price:,.0f} "
                f"(${c.price_per_sqft:,.0f}/sqft, {c.distance_mi:.1f} mi, "
                f"listed {c.age_days}d ago)"
            ),
            contribution=0.0,
        )
        for c in usable
    ]
    return MarketResult(estimate=round(estimate, 2), low=round(low, 2),
                        high=round(high, 2), facts=facts)
