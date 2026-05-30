"""Tests for the closing-milestone orchestrator (U17, R10)."""
from __future__ import annotations

import pytest

from brain.orchestrator.closing import (
    ClosingOrchestrator,
    Counterparty,
    CounterpartyPing,
    FakeCounterpartySink,
    GrpcCounterpartySink,
    Milestone,
)


def test_met_milestone_pings_the_right_counterparty():
    sink = FakeCounterpartySink()
    orch = ClosingOrchestrator(deal_id="deal-1", sink=sink)

    assert orch.record(Milestone.INSPECTION_CLEARED, met=True) is True

    assert sink.pings == [
        CounterpartyPing(
            deal_id="deal-1",
            milestone=Milestone.INSPECTION_CLEARED,
            counterparty=Counterparty.ESCROW,
        )
    ]


def test_each_milestone_routes_to_its_counterparty():
    sink = FakeCounterpartySink()
    orch = ClosingOrchestrator(deal_id="deal-2", sink=sink)

    orch.record(Milestone.EARNEST_DEPOSITED, met=True)
    orch.record(Milestone.TITLE_CLEARED, met=True)
    orch.record(Milestone.FUNDED, met=True)

    by_milestone = {p.milestone: p.counterparty for p in sink.pings}
    assert by_milestone == {
        Milestone.EARNEST_DEPOSITED: Counterparty.ESCROW,
        Milestone.TITLE_CLEARED: Counterparty.TITLE,
        Milestone.FUNDED: Counterparty.LENDER,
    }
    assert len(sink.pings_for(Counterparty.LENDER)) == 1


def test_non_met_milestone_does_not_ping():
    sink = FakeCounterpartySink()
    orch = ClosingOrchestrator(deal_id="deal-3", sink=sink)

    assert orch.record(Milestone.TITLE_CLEARED, met=False) is False

    assert sink.pings == []
    assert orch.state.is_met(Milestone.TITLE_CLEARED) is False


def test_re_recording_a_met_milestone_is_idempotent():
    sink = FakeCounterpartySink()
    orch = ClosingOrchestrator(deal_id="deal-4", sink=sink)

    assert orch.record(Milestone.FUNDED, met=True) is True
    # Same milestone reported met again — no duplicate ping.
    assert orch.record(Milestone.FUNDED, met=True) is False

    assert len(sink.pings) == 1


def test_deal_closes_only_when_all_milestones_met():
    sink = FakeCounterpartySink()
    orch = ClosingOrchestrator(deal_id="deal-5", sink=sink)

    for m in (
        Milestone.INSPECTION_CLEARED,
        Milestone.EARNEST_DEPOSITED,
        Milestone.TITLE_CLEARED,
    ):
        orch.record(m, met=True)
        assert orch.closed is False

    orch.record(Milestone.FUNDED, met=True)
    assert orch.closed is True
    # One ping per milestone; escrow notified for both of its milestones.
    assert len(sink.pings) == 4
    assert len(sink.pings_for(Counterparty.ESCROW)) == 2


def test_grpc_sink_is_a_documented_seam():
    # Import-safe construction (no network), but ping() raises until bound.
    sink = GrpcCounterpartySink()
    with pytest.raises(NotImplementedError):
        sink.ping(
            CounterpartyPing(
                deal_id="x",
                milestone=Milestone.FUNDED,
                counterparty=Counterparty.LENDER,
            )
        )
