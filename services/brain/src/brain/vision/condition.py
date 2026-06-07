"""Map photo findings to a condition score for the AVM (R2).

The valuation model takes an optional ``condition`` in ``[0, 1]`` (U4's photo
signal). This turns the analyzer's structured findings into that number,
deterministically: start neutral, let confident value-features raise it and
visible red-flags (weighted more, since defects matter more than perks) lower it,
clamped to ``[0, 1]``. Pure — no model, no I/O.
"""
from __future__ import annotations

from typing import Iterable

from .schema import Finding

BASE_CONDITION = 0.5
FEATURE_WEIGHT = 0.08
RED_FLAG_WEIGHT = 0.15


def condition_from_findings(
    features: Iterable[Finding],
    red_flags: Iterable[Finding],
    *,
    base: float = BASE_CONDITION,
    feature_weight: float = FEATURE_WEIGHT,
    red_flag_weight: float = RED_FLAG_WEIGHT,
) -> float:
    """Condition score in ``[0, 1]`` from value-features and red-flags.

    Each feature adds ``feature_weight * confidence``; each red-flag subtracts
    ``red_flag_weight * confidence``. Deterministic and order-independent.
    """
    score = base
    for f in features:
        score += feature_weight * float(f.confidence)
    for r in red_flags:
        score -= red_flag_weight * float(r.confidence)
    return max(0.0, min(1.0, score))
