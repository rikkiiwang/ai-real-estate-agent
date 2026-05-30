"""Accuracy gate for the AVM — error against held-out *recorded* sale prices.

Groundedness is not accuracy. The Critic can prove a valuation is *entailed by*
its source comps, but entailment against synthetic comps does not prove the
number is *correct*. This gate measures valuation error against a held-out set
of sales with KNOWN ground-truth prices and refuses to let the MVP claim
accuracy until that error sits inside a stated target band.

.. warning::
   The held-out set here is a **stand-in** for real Travis County recorded
   deed-record sale prices, which are not wired up yet (U2/U5). It is generated
   from an INDEPENDENT, seeded hedonic price function whose parameters and
   sampling ranges differ from the AVM's training generator
   (:mod:`brain.valuation.model`), so the eval genuinely tests generalization
   to out-of-training sales rather than re-scoring training rows. When the real
   deed-record join lands, replace :func:`held_out_sales` with that source and
   keep the rest of this gate unchanged.

The gate returns a structured :class:`AccuracyReport` (per-sale errors plus
aggregate metrics and the pass/fail verdict against the target band) suitable
for logging to the audit store later — this module does not touch the audit DB.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from .features import FEATURE_NAMES
from .model import get_model

# Seed for the held-out sale set. Deliberately different from the model's
# ``_DATA_SEED`` so the eval rows are not the training rows.
_HELD_OUT_SEED: int = 31337
_N_HELD_OUT: int = 400

# Default target band for the gate, stated as fractions (e.g. 0.20 == 20%).
# These are the *ceilings* a passing AVM must stay under. They are parameters:
# callers pass their own band; the defaults are a documented MVP starting point.
DEFAULT_TARGET_MAPE: float = 0.20
DEFAULT_TARGET_MEDIAN_APE: float = 0.15

# Minimum number of held-out sales required to grade accuracy at all. Below this
# the gate reports low confidence rather than a passing grade (R17 honesty).
MIN_COVERAGE: int = 50


def _independent_ground_truth_price(x: np.ndarray) -> np.ndarray:
    """A KNOWN hedonic sale-price function for the held-out set.

    Intentionally *not* identical to the model's training generator: the
    coefficients are perturbed and an extra interaction term is present, so a
    model that merely memorized the training price surface still shows real
    error here. This stands in for the messiness of recorded deed prices.

    Columns follow :data:`brain.valuation.features.FEATURE_NAMES`:
    beds, baths, sqft, lot_sqft, age, garage_spaces, dist_to_center_km, condition.
    """
    beds = x[:, 0]
    baths = x[:, 1]
    sqft = x[:, 2]
    lot = x[:, 3]
    age = x[:, 4]
    garage = x[:, 5]
    dist = x[:, 6]
    condition = x[:, 7]

    price = (
        58_000.0
        + 145.0 * sqft
        + 7.5 * np.sqrt(np.maximum(sqft, 0.0)) * 100.0
        + 11_000.0 * beds
        + 19_000.0 * baths
        + 1.6 * lot
        + 9_500.0 * garage
        - 1_500.0 * age
        - 6_000.0 * dist
        + 118_000.0 * (condition - 0.5)
        # Interaction the AVM never saw in training: condition matters more for
        # larger homes. Keeps the held-out surface honestly out-of-sample.
        + 18.0 * (condition - 0.5) * np.maximum(sqft - 1_800.0, 0.0)
    )
    return np.maximum(price, 40_000.0)


@dataclass(frozen=True)
class SaleError:
    """Per-sale prediction-vs-truth error record (loggable)."""

    index: int
    actual: float
    predicted: float
    abs_error: float
    abs_pct_error: float
    # Group label this sale belongs to (synthetic neighborhood). Carried so the
    # same eval set feeds the fairness audit without recomputation.
    group: str


@dataclass
class AccuracyReport:
    """Structured result of the accuracy gate, suitable for the audit store.

    ``passed`` is the verdict against the target band. ``sufficient_coverage``
    is ``False`` when fewer than :data:`MIN_COVERAGE` sales were available, in
    which case the gate reports low confidence and does **not** pass.
    """

    passed: bool
    sufficient_coverage: bool
    n_sales: int
    mape: float
    median_ape: float
    mean_abs_error: float
    target_mape: float
    target_median_ape: float
    min_coverage: int
    # Note this stands in for real recorded sales; carried into the audit log.
    data_source: str = "held_out_synthetic_stand_in_for_recorded_sales"
    errors: list[SaleError] = field(default_factory=list)

    def to_dict(self) -> dict:
        """A plain-dict view for logging to the audit store later."""
        return asdict(self)


def held_out_sales(
    *,
    n: int = _N_HELD_OUT,
    seed: int = _HELD_OUT_SEED,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Generate the held-out sale set: ``(X, actual_prices, group_labels)``.

    Stand-in for real recorded deed prices. The feature ranges are shifted
    relative to the model's training sampler and prices come from
    :func:`_independent_ground_truth_price`, so this is a true held-out set.

    ``group_labels`` assign each sale a synthetic *neighborhood* derived from
    its location feature; the fairness audit groups valuation outputs by it.
    """
    rng = np.random.default_rng(seed)

    beds = rng.integers(2, 6, size=n).astype(float)
    baths = (rng.integers(2, 9, size=n) / 2.0).astype(float)
    # Shifted ranges vs training (training: 900..4250 base): held-out leans
    # slightly larger and older, exercising generalization not memorization.
    sqft = rng.uniform(950.0, 4400.0, size=n) + (beds - 2) * 240.0
    lot = rng.uniform(2800.0, 12500.0, size=n)
    age = rng.uniform(0.0, 90.0, size=n)
    garage = rng.integers(0, 3, size=n).astype(float)
    dist = rng.uniform(0.0, 26.0, size=n)
    condition = rng.uniform(0.0, 1.0, size=n)

    x = np.column_stack([beds, baths, sqft, lot, age, garage, dist, condition])
    actual = _independent_ground_truth_price(x)
    # Recorded-price noise (~4%), deterministic under the seed.
    actual = np.maximum(actual * (1.0 + rng.normal(0.0, 0.04, size=n)), 40_000.0)

    groups = [neighborhood_for_distance(float(d)) for d in dist]
    return x, actual, groups


def neighborhood_for_distance(dist_km: float) -> str:
    """Bucket a distance-to-center into a synthetic neighborhood label.

    Distance-to-center is a location proxy that, in real data, correlates with
    protected-class composition — exactly the kind of price-encoded feature a
    text deny-list cannot police. Bucketing it gives the fairness audit groups
    to compare valuation outputs across.
    """
    if dist_km < 6.0:
        return "core"
    if dist_km < 13.0:
        return "ring"
    return "edge"


def _predict_batch(x: np.ndarray) -> np.ndarray:
    """Run the cached AVM over a feature matrix, returning point estimates."""
    model = get_model()
    preds = np.empty(x.shape[0], dtype=float)
    for i in range(x.shape[0]):
        preds[i] = model.predict(list(x[i]), sparse_signals=0).estimate
    return preds


def evaluate_accuracy(
    *,
    target_mape: float = DEFAULT_TARGET_MAPE,
    target_median_ape: float = DEFAULT_TARGET_MEDIAN_APE,
    min_coverage: int = MIN_COVERAGE,
    x: Optional[np.ndarray] = None,
    actual: Optional[np.ndarray] = None,
    groups: Optional[list[str]] = None,
) -> AccuracyReport:
    """Run the accuracy gate and return a structured :class:`AccuracyReport`.

    The gate passes only when there is sufficient held-out coverage AND both
    the MAPE and median absolute-percent error sit inside the target band. The
    target band is a parameter (``target_mape`` / ``target_median_ape``): the
    MVP must not claim valuation accuracy unless this returns ``passed=True``.

    ``x`` / ``actual`` / ``groups`` may be supplied to grade against an injected
    set (e.g. real recorded sales once wired); otherwise the held-out stand-in
    set is generated.
    """
    if x is None or actual is None or groups is None:
        x, actual, groups = held_out_sales()

    n = int(x.shape[0])
    predicted = _predict_batch(x)

    abs_err = np.abs(predicted - actual)
    abs_pct = abs_err / np.maximum(np.abs(actual), 1.0)

    errors = [
        SaleError(
            index=i,
            actual=round(float(actual[i]), 2),
            predicted=round(float(predicted[i]), 2),
            abs_error=round(float(abs_err[i]), 2),
            abs_pct_error=round(float(abs_pct[i]), 6),
            group=groups[i],
        )
        for i in range(n)
    ]

    mape = float(np.mean(abs_pct)) if n else 0.0
    median_ape = float(np.median(abs_pct)) if n else 0.0
    mean_abs_error = float(np.mean(abs_err)) if n else 0.0

    sufficient = n >= min_coverage
    within_band = mape <= target_mape and median_ape <= target_median_ape
    passed = bool(sufficient and within_band)

    return AccuracyReport(
        passed=passed,
        sufficient_coverage=sufficient,
        n_sales=n,
        mape=round(mape, 6),
        median_ape=round(median_ape, 6),
        mean_abs_error=round(mean_abs_error, 2),
        target_mape=target_mape,
        target_median_ape=target_median_ape,
        min_coverage=min_coverage,
        errors=errors,
    )
