"""U19 gate tests: valuation accuracy + disparate-impact, both deterministic.

Covers R12/R17. Groundedness (the Critic) is neither accuracy nor fairness, so
these gates check the numbers directly:

* the accuracy gate grades the AVM against a HELD-OUT set of recorded-sale
  stand-ins, passes inside a stated target band and fails outside it, and the
  held-out set is disjoint from the AVM's training rows (not a re-score);
* the disparate-impact gate flags an injected systematic under-valuation of one
  neighborhood proxy group and FAILS, and passes on balanced data;
* both gates return structured, loggable reports.
"""
from __future__ import annotations

import numpy as np

from brain.valuation.accuracy_eval import (
    AccuracyReport,
    SaleError,
    evaluate_accuracy,
    held_out_sales,
)
from brain.valuation.fairness_audit import (
    FairnessReport,
    GroupStat,
    audit_disparate_impact,
    inject_group_bias,
)
from brain.valuation.model import _N_TRAIN, _generate_training_data


# --------------------------------------------------------------------------- #
# Accuracy gate
# --------------------------------------------------------------------------- #


def test_accuracy_gate_passes_inside_realistic_band() -> None:
    report = evaluate_accuracy(target_mape=0.20, target_median_ape=0.15)
    assert isinstance(report, AccuracyReport)
    assert report.passed is True
    assert report.sufficient_coverage is True
    # The error is actually measured, not assumed: real, positive, sub-band.
    assert 0.0 < report.mape <= 0.20
    assert 0.0 < report.median_ape <= 0.15
    assert report.mean_abs_error > 0.0


def test_accuracy_gate_fails_outside_a_strict_band() -> None:
    # An unattainably tight band must fail the gate — the MVP may not claim
    # accuracy it does not have.
    report = evaluate_accuracy(target_mape=0.001, target_median_ape=0.001)
    assert report.passed is False
    # It fails on the band, not on coverage.
    assert report.sufficient_coverage is True
    assert report.mape > report.target_mape


def test_accuracy_gate_is_deterministic() -> None:
    a = evaluate_accuracy()
    b = evaluate_accuracy()
    assert a.mape == b.mape
    assert a.median_ape == b.median_ape
    assert a.n_sales == b.n_sales


def test_low_coverage_reports_low_confidence_not_a_pass() -> None:
    # Slice the held-out set below the coverage floor: the gate reports
    # insufficient coverage and refuses to pass even if the error looks fine.
    x, actual, groups = held_out_sales()
    x, actual, groups = x[:10], actual[:10], groups[:10]
    report = evaluate_accuracy(
        x=x, actual=actual, groups=groups, min_coverage=50
    )
    assert report.n_sales == 10
    assert report.sufficient_coverage is False
    assert report.passed is False


def test_held_out_set_is_disjoint_from_training_rows() -> None:
    # The eval must not be a re-score of training data. Compare the held-out
    # feature matrix against every training row: no exact row may coincide.
    x_eval, _actual, _groups = held_out_sales()
    x_train, _y_train = _generate_training_data()
    assert x_train.shape[0] == _N_TRAIN

    train_rows = {tuple(np.round(r, 6)) for r in x_train}
    eval_rows = {tuple(np.round(r, 6)) for r in x_eval}
    assert train_rows.isdisjoint(eval_rows)


def test_accuracy_report_is_structured_and_loggable() -> None:
    report = evaluate_accuracy()
    payload = report.to_dict()
    assert isinstance(payload, dict)
    # Aggregate fields a downstream audit-log row needs.
    for key in (
        "passed",
        "sufficient_coverage",
        "n_sales",
        "mape",
        "median_ape",
        "target_mape",
        "data_source",
        "errors",
    ):
        assert key in payload
    # The stand-in nature is recorded, so the audit trail is honest about it.
    assert "recorded_sales" in payload["data_source"]
    # Per-sale errors are present and themselves structured.
    assert payload["n_sales"] == len(payload["errors"])
    assert report.errors and isinstance(report.errors[0], SaleError)
    first = payload["errors"][0]
    for key in ("index", "actual", "predicted", "abs_pct_error", "group"):
        assert key in first


# --------------------------------------------------------------------------- #
# Disparate-impact gate
# --------------------------------------------------------------------------- #


def test_disparate_impact_passes_on_balanced_data() -> None:
    report = audit_disparate_impact()
    assert isinstance(report, FairnessReport)
    assert report.passed is True
    assert report.flagged_groups == []
    # Real groups were audited (the neighborhood proxy has >1 bucket).
    assert len({g.group for g in report.group_stats}) >= 2
    assert all(isinstance(g, GroupStat) for g in report.group_stats)


def test_disparate_impact_flags_injected_undervaluation_and_fails() -> None:
    x, actual, groups = held_out_sales()
    # Inflate one neighborhood's recorded prices: the unchanged AVM now
    # systematically under-values that group — price-encoded bias.
    bx, ba, bg = inject_group_bias(
        x, actual, groups, biased_group="edge", undervalue_by=0.25
    )
    report = audit_disparate_impact(x=bx, actual=ba, groups=bg)
    assert report.passed is False
    assert "edge" in report.flagged_groups
    edge = next(g for g in report.group_stats if g.group == "edge")
    assert edge.flagged is True
    assert edge.flag_reasons  # explains WHY it was flagged, for the audit log
    # The disparity is directional under-valuation, not random noise.
    assert edge.mean_signed_bias < 0


def test_disparate_impact_is_deterministic() -> None:
    a = audit_disparate_impact()
    b = audit_disparate_impact()
    assert a.passed == b.passed
    assert a.overall_mean_abs_pct_error == b.overall_mean_abs_pct_error
    assert [g.mean_abs_pct_error for g in a.group_stats] == [
        g.mean_abs_pct_error for g in b.group_stats
    ]


def test_threshold_is_a_parameter() -> None:
    # A near-zero undervaluation tolerance flags even the mild residual bias
    # present in balanced data; the lenient default does not. Proves the gate
    # is tunable rather than hard-coded.
    strict = audit_disparate_impact(max_undervaluation=0.001, max_error_gap=10.0)
    assert strict.passed is False
    lenient = audit_disparate_impact()
    assert lenient.passed is True


def test_fairness_report_is_structured_and_loggable() -> None:
    report = audit_disparate_impact()
    payload = report.to_dict()
    assert isinstance(payload, dict)
    for key in (
        "passed",
        "n_records",
        "overall_mean_abs_pct_error",
        "flagged_groups",
        "group_stats",
        "audit_target",
    ):
        assert key in payload
    assert payload["group_stats"]
    first = payload["group_stats"][0]
    for key in (
        "group",
        "n",
        "mean_prediction",
        "mean_actual",
        "mean_abs_pct_error",
        "mean_signed_bias",
        "flagged",
    ):
        assert key in first


def test_accuracy_and_fairness_share_one_eval_set() -> None:
    # Both gates draw the same held-out set, so a single eval feeds both the
    # accuracy report and the per-group audit (one audit-log episode).
    x, actual, groups = held_out_sales()
    acc = evaluate_accuracy(x=x, actual=actual, groups=groups)
    fair = audit_disparate_impact(x=x, actual=actual, groups=groups)
    assert acc.n_sales == fair.n_records
    # The accuracy per-sale groups are exactly the audited group set.
    assert {e.group for e in acc.errors} == {g.group for g in fair.group_stats}
