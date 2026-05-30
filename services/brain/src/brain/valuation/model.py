"""Gradient-boosting AVM trained on a hermetic synthetic dataset.

The model is a :class:`sklearn.ensemble.GradientBoostingRegressor` fit over the
fixed feature vector (see :mod:`brain.valuation.features`). Training data is
generated in-process from a deterministic, seeded synthetic price function plus
noise — no external data, no network — so training is hermetic and every
prediction is stable across calls. The trained model is cached process-wide and
trained lazily on first use.

The uncertainty band is a quantile band from an ensemble of quantile-loss
boosters (lower/upper), widened when the input is sparse (e.g. no photo-derived
condition signal) so low-coverage inputs never produce false precision.

Per-feature contributions are derived by ablating each feature to the training
mean and measuring the prediction delta, giving a source-citable dollar effect
per feature for the Critic.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

from . import features as feat

# Deterministic seeds so the dataset, model, and predictions are reproducible.
_DATA_SEED: int = 20260529
_MODEL_SEED: int = 7
_N_TRAIN: int = 4000

# Quantiles for the uncertainty band (≈80% central interval).
_Q_LOW: float = 0.10
_Q_HIGH: float = 0.90

# Extra band widening (fraction of the estimate) applied per sparse signal, so a
# low-coverage input widens rather than asserting a confident point estimate.
_SPARSE_WIDEN: float = 0.06


@dataclass
class Prediction:
    estimate: float
    low: float
    high: float
    # Dollar contribution per feature, aligned to ``features.FEATURE_NAMES``.
    contributions: list[float]


def _synthetic_price(x: np.ndarray) -> np.ndarray:
    """A known hedonic price function over the feature matrix ``x``.

    Columns follow ``features.FEATURE_NAMES``:
    beds, baths, sqft, lot_sqft, age, garage_spaces, dist_to_center_km, condition.
    The function is intentionally non-linear (sqft has the dominant, mildly
    concave effect; age and distance depreciate) so a gradient booster has
    structure to learn.
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
        60_000.0
        + 140.0 * sqft
        + 8.0 * np.sqrt(np.maximum(sqft, 0.0)) * 100.0  # mild concavity in sqft
        + 12_000.0 * beds
        + 18_000.0 * baths
        + 1.5 * lot
        + 9_000.0 * garage
        - 1_400.0 * age
        - 6_500.0 * dist
        + 120_000.0 * (condition - 0.5)  # condition swings ±60k around neutral
    )
    return np.maximum(price, 40_000.0)


def _generate_training_data() -> tuple[np.ndarray, np.ndarray]:
    """Build a deterministic ``(X, y)`` synthetic training set."""
    rng = np.random.default_rng(_DATA_SEED)
    n = _N_TRAIN

    beds = rng.integers(2, 6, size=n).astype(float)
    baths = (rng.integers(2, 9, size=n) / 2.0).astype(float)  # 1.0..4.0
    sqft = rng.uniform(900.0, 4250.0, size=n) + (beds - 2) * 250.0
    lot = rng.uniform(3000.0, 12000.0, size=n)
    age = rng.uniform(0.0, 80.0, size=n)
    garage = rng.integers(0, 3, size=n).astype(float)
    dist = rng.uniform(0.0, 25.0, size=n)
    condition = rng.uniform(0.0, 1.0, size=n)

    x = np.column_stack([beds, baths, sqft, lot, age, garage, dist, condition])
    y = _synthetic_price(x)
    # Heteroscedastic-ish multiplicative noise (~5%): realistic, still learnable.
    y = y * (1.0 + rng.normal(0.0, 0.05, size=n))
    return x, np.maximum(y, 40_000.0)


class ValuationModel:
    """A trained AVM: point estimate, quantile band, and feature contributions."""

    def __init__(self) -> None:
        x, y = _generate_training_data()
        self._x_mean = x.mean(axis=0)

        common = dict(
            n_estimators=300,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.9,
            random_state=_MODEL_SEED,
        )
        self._point = GradientBoostingRegressor(loss="squared_error", **common)
        self._lower = GradientBoostingRegressor(
            loss="quantile", alpha=_Q_LOW, **common
        )
        self._upper = GradientBoostingRegressor(
            loss="quantile", alpha=_Q_HIGH, **common
        )
        self._point.fit(x, y)
        self._lower.fit(x, y)
        self._upper.fit(x, y)

    def _contributions(self, vec: np.ndarray, estimate: float) -> list[float]:
        """Dollar effect of each feature, by ablating it to the training mean."""
        contribs: list[float] = []
        for i in range(vec.shape[0]):
            ablated = vec.copy()
            ablated[i] = self._x_mean[i]
            base = float(self._point.predict(ablated.reshape(1, -1))[0])
            contribs.append(estimate - base)
        return contribs

    def predict(self, vector: list[float], *, sparse_signals: int = 0) -> Prediction:
        """Predict from a feature vector.

        ``sparse_signals`` is the count of missing/imputed inputs (e.g. a missing
        photo-condition signal); each one widens the band so sparse inputs surface
        uncertainty instead of a falsely precise number.
        """
        vec = np.asarray(vector, dtype=float)
        row = vec.reshape(1, -1)

        estimate = float(self._point.predict(row)[0])
        low = float(self._lower.predict(row)[0])
        high = float(self._upper.predict(row)[0])

        # Keep the band ordered and bracketing the estimate even if quantile
        # learners cross on an out-of-distribution point.
        low = min(low, estimate)
        high = max(high, estimate)

        if sparse_signals > 0:
            widen = estimate * _SPARSE_WIDEN * sparse_signals
            low -= widen
            high += widen

        low = max(0.0, low)
        contributions = self._contributions(vec, estimate)
        return Prediction(
            estimate=estimate, low=low, high=high, contributions=contributions
        )


# Process-wide cache: the AVM is trained once, lazily, behind a lock.
_MODEL: ValuationModel | None = None
_MODEL_LOCK = threading.Lock()


def get_model() -> ValuationModel:
    """Return the cached AVM, training it on first use (thread-safe)."""
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                _MODEL = ValuationModel()
    return _MODEL
