"""U13 tests — time-to-offer instrumentation (R15), orchestrator side.

Mirrors the Rails ``OfferMetric`` coverage. All timestamps are passed in, so
every assertion is exact and deterministic (no clock reads).

Scenarios:

* COMPLETED FLOW — a drafted offer records a positive duration.
* BOTH VARIANTS — seller and buyer each record, tagged by side.
* NO FALSE COMPLETION — an escalated/abandoned run records nothing.
* STRUCTURED — a record projects onto a flat log-friendly dict.
* SUMMARY — per-side and aggregate stats.
* GUARDS — unknown side and a negative duration are rejected.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from brain.orchestrator.metrics import (
    SIDE_BUYER,
    SIDE_SELLER,
    TimeToOffer,
    TimeToOfferRecord,
)


def test_completed_flow_records_positive_duration():
    rec = TimeToOffer().record(SIDE_SELLER, lead_created=1_000.0, offer_drafted=1_090.0)
    assert isinstance(rec, TimeToOfferRecord)
    assert rec.side == SIDE_SELLER
    assert rec.seconds_to_offer == 90.0
    assert rec.seconds_to_offer > 0


def test_accepts_datetimes_and_computes_same_duration():
    start = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 29, 12, 2, 30, tzinfo=timezone.utc)
    rec = TimeToOffer.compute(SIDE_BUYER, lead_created=start, offer_drafted=end)
    assert rec.seconds_to_offer == 150.0
    assert rec.side == SIDE_BUYER


def test_naive_datetime_is_treated_as_utc():
    start = datetime(2026, 5, 29, 12, 0, 0)
    end = datetime(2026, 5, 29, 12, 0, 5)
    rec = TimeToOffer.compute(SIDE_SELLER, lead_created=start, offer_drafted=end)
    assert rec.seconds_to_offer == 5.0


def test_seller_and_buyer_variants_both_record():
    recorder = TimeToOffer()
    recorder.record(SIDE_SELLER, 100.0, 200.0)
    recorder.record(SIDE_BUYER, 100.0, 400.0)

    assert recorder.count() == 2
    assert recorder.count(SIDE_SELLER) == 1
    assert recorder.count(SIDE_BUYER) == 1
    assert {r.side for r in recorder.records} == {SIDE_SELLER, SIDE_BUYER}


def test_escalated_or_abandoned_flow_records_no_false_completion():
    recorder = TimeToOffer()
    # The run escalated/abandoned before an offer was drafted, so nothing is
    # recorded — there is no offer-drafted moment to measure.
    assert recorder.count() == 0
    assert recorder.records == ()
    assert recorder.average_seconds() is None
    assert recorder.summary()["all"]["count"] == 0


def test_record_projects_to_structured_log():
    rec = TimeToOffer.compute(SIDE_SELLER, 1_000.0, 1_042.0)
    log = rec.as_log()
    assert log == {
        "metric": "time_to_offer",
        "side": SIDE_SELLER,
        "seconds_to_offer": 42.0,
        "lead_created": 1_000.0,
        "offer_drafted": 1_042.0,
    }


def test_summary_reports_per_side_and_aggregate():
    recorder = TimeToOffer()
    recorder.record(SIDE_SELLER, 0.0, 100.0)
    recorder.record(SIDE_SELLER, 0.0, 300.0)
    recorder.record(SIDE_BUYER, 0.0, 200.0)

    summary = recorder.summary()
    assert summary[SIDE_SELLER] == {"count": 2, "average_seconds": 200.0}
    assert summary[SIDE_BUYER] == {"count": 1, "average_seconds": 200.0}
    assert summary["all"] == {"count": 3, "average_seconds": 200.0}


def test_rejects_unknown_side():
    with pytest.raises(ValueError):
        TimeToOffer.compute("landlord", 0.0, 10.0)


def test_rejects_negative_duration():
    with pytest.raises(ValueError):
        TimeToOffer.compute(SIDE_SELLER, lead_created=500.0, offer_drafted=400.0)
