"""Disparate-impact gate — audits AVM *outputs* across proxy-feature groups.

A text Fair-Housing deny-list scans *wording*; it can catch "this is a great
family neighborhood" but is blind to bias that lives in the *numbers*. If the
AVM systematically under-values homes in a neighborhood whose location proxy
correlates with a protected class, no deny-list will ever see it — the bias is
price-encoded, not word-encoded. That is precisely why this gate exists: it
groups valuation outputs by a protected-class-correlated proxy feature
(synthetic neighborhood derived from distance-to-center / location) and flags
systematic disparity in either valuation error or directional under-valuation.

A detected disparity FAILS the gate and blocks the pilot. The gate returns a
structured :class:`FairnessReport` (group stats + the flagged groups + the
verdict) suitable for logging to the audit store later — no audit DB here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from .accuracy_eval import (
    _independent_ground_truth_price,
    _predict_batch,
    held_out_sales,
    neighborhood_for_distance,
)

# Default disparity thresholds (parameters; callers may override).
# A group whose mean absolute-percent error exceeds the overall mean error by
# more than this *relative* margin is flagged.
DEFAULT_MAX_ERROR_GAP: float = 0.50
# A group whose mean signed valuation bias (predicted/actual - 1) is more
# negative than this is flagged as systematically under-valued, even if its
# magnitude error looks acceptable — directional bias is the fair-lending harm.
DEFAULT_MAX_UNDERVALUATION: float = 0.05


@dataclass
class GroupStat:
    """Per-group valuation statistics over the audited set (loggable)."""

    group: str
    n: int
    mean_prediction: float
    mean_actual: float
    mean_abs_pct_error: float
    # Signed bias: mean(predicted/actual - 1). Negative == under-valued.
    mean_signed_bias: float
    flagged: bool
    flag_reasons: list[str] = field(default_factory=list)


@dataclass
class FairnessReport:
    """Structured result of the disparate-impact gate, for the audit store.

    ``passed=False`` means a systematic disparity was detected and the pilot is
    blocked. ``flagged_groups`` names the offending groups for the audit log.
    """

    passed: bool
    n_records: int
    overall_mean_abs_pct_error: float
    max_error_gap: float
    max_undervaluation: float
    flagged_groups: list[str]
    group_stats: list[GroupStat]
    audit_target: str = "valuation_outputs_by_neighborhood_proxy"

    def to_dict(self) -> dict:
        """A plain-dict view for logging to the audit store later."""
        return asdict(self)


def audit_disparate_impact(
    *,
    max_error_gap: float = DEFAULT_MAX_ERROR_GAP,
    max_undervaluation: float = DEFAULT_MAX_UNDERVALUATION,
    x: Optional[np.ndarray] = None,
    actual: Optional[np.ndarray] = None,
    groups: Optional[list[str]] = None,
) -> FairnessReport:
    """Audit valuation outputs for systematic disparity across proxy groups.

    For each group (synthetic neighborhood proxy) the gate compares mean
    valuation error and signed bias against the overall population. A group is
    flagged when either:

    * its mean absolute-percent error exceeds the overall mean by more than
      ``max_error_gap`` (relative) — the AVM is simply *worse* there, or
    * its mean signed bias is below ``-max_undervaluation`` — the AVM
      *systematically under-values* it (the fair-lending harm).

    Any flagged group fails the gate (``passed=False``) and blocks the pilot.
    Both thresholds are parameters. ``x`` / ``actual`` / ``groups`` may be
    injected; otherwise the held-out stand-in set is used.
    """
    if x is None or actual is None or groups is None:
        x, actual, groups = held_out_sales()

    actual = np.asarray(actual, dtype=float)
    predicted = _predict_batch(x)

    abs_pct = np.abs(predicted - actual) / np.maximum(np.abs(actual), 1.0)
    signed_bias = predicted / np.maximum(np.abs(actual), 1.0) - 1.0

    overall_mape = float(np.mean(abs_pct)) if len(abs_pct) else 0.0

    group_names = sorted(set(groups))
    groups_arr = np.asarray(groups, dtype=object)

    stats: list[GroupStat] = []
    flagged: list[str] = []
    for name in group_names:
        mask = groups_arr == name
        g_abs_pct = abs_pct[mask]
        g_bias = signed_bias[mask]
        g_pred = predicted[mask]
        g_actual = actual[mask]
        n_g = int(mask.sum())

        g_mape = float(np.mean(g_abs_pct)) if n_g else 0.0
        g_signed = float(np.mean(g_bias)) if n_g else 0.0

        reasons: list[str] = []
        # Relative error gap vs the overall population.
        if overall_mape > 0 and (g_mape - overall_mape) / overall_mape > max_error_gap:
            reasons.append(
                f"error_gap: group MAPE {g_mape:.4f} exceeds overall "
                f"{overall_mape:.4f} by >{max_error_gap:.0%}"
            )
        # Directional systematic under-valuation.
        if g_signed < -max_undervaluation:
            reasons.append(
                f"undervaluation: mean signed bias {g_signed:.4f} "
                f"below -{max_undervaluation:.4f}"
            )

        is_flagged = bool(reasons)
        if is_flagged:
            flagged.append(name)

        stats.append(
            GroupStat(
                group=name,
                n=n_g,
                mean_prediction=round(float(np.mean(g_pred)) if n_g else 0.0, 2),
                mean_actual=round(float(np.mean(g_actual)) if n_g else 0.0, 2),
                mean_abs_pct_error=round(g_mape, 6),
                mean_signed_bias=round(g_signed, 6),
                flagged=is_flagged,
                flag_reasons=reasons,
            )
        )

    return FairnessReport(
        passed=not flagged,
        n_records=int(len(actual)),
        overall_mean_abs_pct_error=round(overall_mape, 6),
        max_error_gap=max_error_gap,
        max_undervaluation=max_undervaluation,
        flagged_groups=flagged,
        group_stats=stats,
    )


def inject_group_bias(
    x: np.ndarray,
    actual: np.ndarray,
    groups: list[str],
    *,
    biased_group: str,
    undervalue_by: float = 0.25,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return a copy of the audit set with one group's *recorded* prices raised.

    Used to characterize the gate: by inflating ``biased_group``'s ground-truth
    sale prices, the unchanged AVM now systematically under-predicts that group,
    reproducing the price-encoded disparity the gate must catch. The features
    (and thus AVM predictions) are untouched; only the recorded prices move, so
    this models "the AVM lags real prices for this neighborhood".
    """
    actual = np.asarray(actual, dtype=float).copy()
    groups_arr = np.asarray(groups, dtype=object)
    mask = groups_arr == biased_group
    actual[mask] = actual[mask] * (1.0 + undervalue_by)
    return x, actual, list(groups)
