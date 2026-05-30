"""Closing-milestone orchestration (U17, R10) — simulated counterparts.

After an offer is signed, a real estate deal closes through a fixed sequence of
milestones. This module drives that sequence and, as each milestone is *met*,
pings the right simulated counterparty (escrow / title / lender) so downstream
parties advance in step. Real escrow/title/lender integrations are explicitly
DEFERRED (see the plan's Scope Boundaries) and sit behind the
:class:`CounterpartySink` interface, exactly mirroring the injected-sink pattern
the Closer uses (``OfferSink``/``HandoffSink``): tests use
:class:`FakeCounterpartySink`, and a future ``GrpcCounterpartySink`` binds the
real RPC without touching this orchestration.

The contract is deterministic and stdlib-only:

* Each :class:`Milestone` maps to exactly one :class:`Counterparty` that must be
  notified when (and only when) the milestone is *met*.
* Recording a milestone as met emits one :class:`CounterpartyPing` to the sink;
  recording it as NOT met emits nothing.
* Re-recording an already-pinged milestone is idempotent — a counterparty is
  pinged at most once per milestone.
* When every milestone is met, the deal is :attr:`ClosingState.closed`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Protocol


# --------------------------------------------------------------------------- #
# Milestones, counterparties, and their fixed mapping.
# --------------------------------------------------------------------------- #
class Milestone(str, Enum):
    """The closing milestones, in the order a deal clears them.

    Order is documentation/iteration convenience; the orchestrator does not
    force a sequence — it pings whichever milestone is reported met. The MVP
    keeps the canonical four.
    """

    INSPECTION_CLEARED = "inspection_cleared"
    EARNEST_DEPOSITED = "earnest_deposited"
    TITLE_CLEARED = "title_cleared"
    FUNDED = "funded"


class Counterparty(str, Enum):
    """The simulated external party notified for a milestone."""

    ESCROW = "escrow"
    TITLE = "title"
    LENDER = "lender"


# Which counterparty must be pinged when a milestone is met. This is the
# load-bearing routing table: a met milestone notifies exactly one counterpart.
MILESTONE_COUNTERPARTY: Dict[Milestone, Counterparty] = {
    Milestone.INSPECTION_CLEARED: Counterparty.ESCROW,
    Milestone.EARNEST_DEPOSITED: Counterparty.ESCROW,
    Milestone.TITLE_CLEARED: Counterparty.TITLE,
    Milestone.FUNDED: Counterparty.LENDER,
}


@dataclass(frozen=True)
class CounterpartyPing:
    """A single notification sent to a simulated counterparty.

    ``deal_id`` ties the ping to a transaction; ``milestone`` is the event that
    triggered it; ``counterparty`` is who was notified (per
    :data:`MILESTONE_COUNTERPARTY`).
    """

    deal_id: str
    milestone: Milestone
    counterparty: Counterparty


# --------------------------------------------------------------------------- #
# The injected counterparty sink (real integrations deferred behind it).
# --------------------------------------------------------------------------- #
class CounterpartySink(Protocol):
    """Where a :class:`CounterpartyPing` is delivered (injected, so tests fake).

    Implementations notify the real escrow/title/lender systems. The MVP only
    ever uses :class:`FakeCounterpartySink`; the real binding is a deferred
    follow-up behind this same interface.
    """

    def ping(self, ping: CounterpartyPing) -> None:  # pragma: no cover - protocol
        ...


@dataclass
class FakeCounterpartySink:
    """In-memory sink recording every ping — for tests and dry runs.

    Performs NO network I/O. Inspect :attr:`pings` to assert which
    counterparties were notified for which milestones.
    """

    pings: List[CounterpartyPing] = field(default_factory=list)

    def ping(self, ping: CounterpartyPing) -> None:
        self.pings.append(ping)

    def pings_for(self, counterparty: Counterparty) -> List[CounterpartyPing]:
        """Return the recorded pings sent to ``counterparty`` (test helper)."""
        return [p for p in self.pings if p.counterparty is counterparty]


class GrpcCounterpartySink:
    """Notify real escrow/title/lender systems over gRPC — DOCUMENTED SEAM.

    Mirrors :class:`brain.orchestrator.closer.DomainOfferSink`: import-safe and
    connection-free at construction; the real RPC is a deliberate follow-up and
    is NOT wired in this unit. Calling :meth:`ping` raises so the unbound seam is
    explicit rather than a silent no-op. Use :class:`FakeCounterpartySink` for
    tests/dry runs.
    """

    def __init__(self, target: str = "localhost:50051") -> None:
        self._target = target
        self._channel = None  # lazily created grpc.Channel (follow-up)

    def ping(self, ping: CounterpartyPing) -> None:
        raise NotImplementedError(
            "GrpcCounterpartySink is a documented seam: bind the escrow/title/"
            "lender RPC as a deferred follow-up. Use FakeCounterpartySink for "
            "tests/dry runs."
        )


# --------------------------------------------------------------------------- #
# The orchestrator.
# --------------------------------------------------------------------------- #
@dataclass
class ClosingState:
    """The milestone status of one deal and the pings already emitted.

    ``met`` records which milestones are satisfied; ``pinged`` records which have
    already notified their counterparty (so re-recording is idempotent).
    """

    deal_id: str
    met: Dict[Milestone, bool] = field(default_factory=dict)
    pinged: set = field(default_factory=set)

    def is_met(self, milestone: Milestone) -> bool:
        return self.met.get(milestone, False)

    @property
    def closed(self) -> bool:
        """True once every milestone is met."""
        return all(self.met.get(m, False) for m in Milestone)


class ClosingOrchestrator:
    """Drives closing milestones, pinging simulated counterparts as they're met.

    Injected with a :class:`CounterpartySink` (where pings land). Deterministic,
    stdlib-only; the real counterparty integrations are deferred behind the sink.
    """

    def __init__(self, deal_id: str, sink: CounterpartySink) -> None:
        self._sink = sink
        self.state = ClosingState(deal_id=deal_id)

    def record(self, milestone: Milestone, *, met: bool) -> bool:
        """Record a milestone's status; ping its counterparty iff newly met.

        Returns True iff a counterparty ping was emitted by this call. A
        not-met milestone emits nothing; an already-pinged milestone is
        idempotent (no duplicate ping).
        """
        self.state.met[milestone] = met
        if not met:
            return False
        if milestone in self.state.pinged:
            return False
        counterparty = MILESTONE_COUNTERPARTY[milestone]
        self._sink.ping(
            CounterpartyPing(
                deal_id=self.state.deal_id,
                milestone=milestone,
                counterparty=counterparty,
            )
        )
        self.state.pinged.add(milestone)
        return True

    @property
    def closed(self) -> bool:
        return self.state.closed


__all__ = [
    "Milestone",
    "Counterparty",
    "MILESTONE_COUNTERPARTY",
    "CounterpartyPing",
    "CounterpartySink",
    "FakeCounterpartySink",
    "GrpcCounterpartySink",
    "ClosingState",
    "ClosingOrchestrator",
]
