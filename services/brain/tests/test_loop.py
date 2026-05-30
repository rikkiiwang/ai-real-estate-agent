"""U16 tests — one-property acquire->list->resell loop (the demo spine).

Covers R14 on a SINGLE property: it is acquired on the SELLER side (a drafted
acquisition offer), ``listed``, re-discovered and offered on the BUYER side
(reusing matching + the buyer Closer adapter), and reaches ``sold``. The loop
adds no agent logic — it orchestrates the already-built units — so these tests
assert the orchestration invariants:

* HAPPY PATH / INTEGRATION — the full loop runs end-to-end on one address: a
  property acquired via the seller flow becomes matchable in the buyer flow and
  reaches ``sold``; both an acquisition offer and a resale offer are drafted,
  both ``awaiting_broker`` (never signed).
* SAME IDENTITY — the SAME property id/address flows through both sides (the
  buyer flow matches the very property the seller flow acquired).
* GUARDED LIFECYCLE — transitions are guarded (cannot list before acquired;
  cannot sell before under_offer; no backward/skip moves) and raise the typed
  :class:`IllegalTransition`.

Hermetic + deterministic: in-memory fakes for every sink and a pinned clock.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest

from brain.lawyer.handoff import Decision, FakeHandoffSink
from brain.orchestrator.buyer_intake import INTENT_HIGH, buyer_intake
from brain.orchestrator.closer import (
    AuthorizedBand,
    FakeOfferSink,
    OfferStatus,
)
from brain.orchestrator.loop import (
    IllegalTransition,
    LoopResult,
    PropertyLoop,
    PropertyState,
    PropertyStatus,
    run_loop,
)
from brain.orchestrator.seller_intake import INTENT_HIGH as SELLER_HIGH, seller_intake
from brain.valuation import Valuation


# --------------------------------------------------------------------------- #
# Fixtures / helpers.
# --------------------------------------------------------------------------- #
ADDRESS = "789 Demo Spine Dr, Austin, TX 78704"
PROPERTY_ID = "prop-demo-1"
FIXED_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

# Acquisition: buy below the AVM estimate. Resale: sell at-or-near it.
ACQUISITION_BAND = AuthorizedBand(open_price=450_000.0, ceiling=470_000.0)
RESALE_BAND = AuthorizedBand(open_price=480_000.0, ceiling=500_000.0)


@dataclass(frozen=True)
class _Terms:
    """Buyer deal-terms stand-in (no custom clause -> no UPL refusal)."""

    custom_clause_request: Optional[str] = None
    valuation: Optional[Valuation] = None


def _seller_request():
    return seller_intake(ADDRESS, SELLER_HIGH, {"timeline": "30 days"})


def _buyer_request():
    # Criteria the listed property will satisfy (see _listing_extras).
    return buyer_intake(
        INTENT_HIGH,
        {"max_price": 510_000.0, "min_beds": 3, "location": "Austin"},
    )


def _valuation():
    return Valuation(sufficient_data=True, estimate=490_000.0, low=470_000.0, high=510_000.0)


def _listing_extras():
    # Neutral listing facts so the buyer's criteria actually match the listing.
    return {"beds": 4, "price": 495_000.0, "location": "Austin"}


def _run(**overrides):
    offer_sink = FakeOfferSink()
    handoff_sink = FakeHandoffSink()
    loop = PropertyLoop(offer_sink=offer_sink, handoff_sink=handoff_sink, now=FIXED_NOW)
    kwargs = dict(
        property_id=PROPERTY_ID,
        seller_request=_seller_request(),
        seller_valuation=_valuation(),
        acquisition_band=ACQUISITION_BAND,
        buyer_request=_buyer_request(),
        resale_band=RESALE_BAND,
        resale_terms=_Terms(valuation=_valuation()),
        lead_id="lead-loop-1",
        seller_name="Sam Seller",
        listing_extras=_listing_extras(),
    )
    kwargs.update(overrides)
    result = loop.run_loop(**kwargs)
    return result, offer_sink, handoff_sink


# --------------------------------------------------------------------------- #
# HAPPY PATH / INTEGRATION — full loop end-to-end on one address.
# --------------------------------------------------------------------------- #
def test_full_loop_reaches_sold_on_one_address():
    result, offer_sink, handoff_sink = _run()

    assert isinstance(result, LoopResult)
    # The property completed acquire -> list -> under_offer -> sold.
    assert result.sold is True
    assert result.property_state.status is PropertyStatus.SOLD
    assert result.property_state.history == [
        PropertyStatus.ACQUIRED,
        PropertyStatus.LISTED,
        PropertyStatus.UNDER_OFFER,
        PropertyStatus.SOLD,
    ]

    # Two offers were drafted (acquisition + resale), both awaiting broker,
    # never signed. Nothing escalated to a human.
    assert len(offer_sink.offers) == 2
    for offer in offer_sink.offers:
        assert offer.status is OfferStatus.AWAITING_BROKER
        assert offer.signed is False
    assert handoff_sink.packets == []  # no escalations on the happy loop

    # Acquisition proceeded (seller side) and resale proceeded (buyer side).
    assert result.acquisition.decision is Decision.PROCEED
    assert result.acquisition.offer is not None
    assert result.resale.decision is Decision.PROCEED
    assert result.resale.offer is not None
    assert result.resale.side == "buyer"
    assert result.resale.drafted_at == FIXED_NOW


def test_acquired_property_becomes_matchable_in_buyer_flow():
    """A property acquired via the seller flow is matched by the buyer flow."""
    result, _, _ = _run()
    # The buyer flow re-discovered the listed property as a match.
    assert result.match is not None
    assert result.match.address == ADDRESS
    assert result.match.listing_id == PROPERTY_ID


# --------------------------------------------------------------------------- #
# SAME IDENTITY — one property flows through both sides.
# --------------------------------------------------------------------------- #
def test_same_property_identity_flows_through_both_sides():
    result, _, _ = _run()
    # Seller side acquired it under this address...
    assert result.property_state.address == ADDRESS
    assert result.property_state.property_id == PROPERTY_ID
    # ...and the buyer side matched the exact same identity (id + address).
    assert result.match.listing_id == result.property_state.property_id
    assert result.match.address == result.property_state.address
    # The resale purchase offer was drafted on that same address.
    assert result.resale.offer.form.to_dict()["blanks"]["property_address"] == ADDRESS


def test_module_level_run_loop_wrapper_drives_full_loop():
    """The convenience ``run_loop`` wrapper reaches the same sold end-state."""
    offer_sink = FakeOfferSink()
    result = run_loop(
        property_id=PROPERTY_ID,
        seller_request=_seller_request(),
        seller_valuation=_valuation(),
        acquisition_band=ACQUISITION_BAND,
        buyer_request=_buyer_request(),
        resale_band=RESALE_BAND,
        resale_terms=_Terms(valuation=_valuation()),
        lead_id="lead-loop-2",
        seller_name="Sam Seller",
        listing_extras=_listing_extras(),
        offer_sink=offer_sink,
        now=FIXED_NOW,
    )
    assert result.sold is True
    assert len(offer_sink.offers) == 2


# --------------------------------------------------------------------------- #
# GUARDED LIFECYCLE — transitions are guarded; illegal moves raise.
# --------------------------------------------------------------------------- #
def test_cannot_list_before_acquired_is_a_construction_invariant():
    """A property enters at ACQUIRED; listing is only legal from there."""
    prop = PropertyState(property_id=PROPERTY_ID, address=ADDRESS)
    assert prop.status is PropertyStatus.ACQUIRED
    # Listing from ACQUIRED is the one legal move.
    prop.list_()
    assert prop.status is PropertyStatus.LISTED


def test_cannot_sell_before_under_offer_raises():
    prop = PropertyState(property_id=PROPERTY_ID, address=ADDRESS)
    prop.list_()  # ACQUIRED -> LISTED
    # Selling from LISTED skips UNDER_OFFER -> illegal.
    with pytest.raises(IllegalTransition):
        prop.sell()
    assert prop.status is PropertyStatus.LISTED  # unchanged


def test_cannot_skip_states_from_acquired_to_under_offer_raises():
    prop = PropertyState(property_id=PROPERTY_ID, address=ADDRESS)
    with pytest.raises(IllegalTransition):
        prop.mark_under_offer()  # ACQUIRED -> UNDER_OFFER skips LISTED
    assert prop.status is PropertyStatus.ACQUIRED


def test_no_backward_or_terminal_moves():
    prop = PropertyState(property_id=PROPERTY_ID, address=ADDRESS)
    prop.list_()
    prop.mark_under_offer()
    prop.sell()
    assert prop.status is PropertyStatus.SOLD
    # SOLD is terminal: any further move raises.
    with pytest.raises(IllegalTransition):
        prop.list_()
    with pytest.raises(IllegalTransition):
        prop.sell()


def test_illegal_transition_carries_states():
    prop = PropertyState(property_id=PROPERTY_ID, address=ADDRESS)
    prop.list_()
    with pytest.raises(IllegalTransition) as exc_info:
        prop.sell()
    err = exc_info.value
    assert err.current is PropertyStatus.LISTED
    assert err.target is PropertyStatus.SOLD


# --------------------------------------------------------------------------- #
# REQUIRED-FIELD guards on PropertyState identity.
# --------------------------------------------------------------------------- #
def test_property_state_requires_identity():
    with pytest.raises(ValueError):
        PropertyState(property_id="", address=ADDRESS)
    with pytest.raises(ValueError):
        PropertyState(property_id=PROPERTY_ID, address="  ")


# --------------------------------------------------------------------------- #
# LOOP REFUSALS — an escalated acquisition / no buyer match aborts honestly.
# --------------------------------------------------------------------------- #
def test_out_of_band_acquisition_aborts_loop_no_property_sold():
    """An out-of-band acquisition escalates; the loop refuses to fake a sale."""
    with pytest.raises(ValueError):
        _run(acquisition_price=999_999.0)  # above the acquisition ceiling


def test_unmatched_listing_aborts_loop():
    """If the buyer criteria don't match the listing, the loop aborts."""
    # Over-constrained buyer (needs 6 beds) cannot match the 4-bed listing.
    over_constrained = buyer_intake(
        INTENT_HIGH, {"max_price": 510_000.0, "min_beds": 6, "location": "Austin"}
    )
    with pytest.raises(ValueError):
        _run(buyer_request=over_constrained)
