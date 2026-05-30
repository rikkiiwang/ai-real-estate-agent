"""U15 tests — buyer purchase-offer draft + broker gate (thin Closer, buyer side).

Covers AE4 / R8 / R15 on the BUYER side, REUSING the seller-side Closer's
guardrail (band + UPL + handoff + awaiting-broker emission) via the thin adapter
in :mod:`brain.orchestrator.buyer_offer`.

Band fixture {open 470000, ceiling 485000} on a matched property:

* an in-band buyer counter (480000) IS allowed -> a filled TREC One-to-Four
  Family resale PURCHASE form lands in the offer sink in ``awaiting_broker``
  state, never signed;
* an above-ceiling buyer counter (486000) NEVER auto-offers -> it escalates and
  NO offer is emitted;
* a custom-clause request escalates (UPL) and NO clause text is generated (the
  reused form-fill refuses; the offer sink stays empty);
* every result carries ``side == "buyer"`` and a ``drafted_at`` timestamp on a
  real draft (and NO timestamp on an escalation), for the metric layer (R15).

No network: exercised with in-memory fakes only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest

from brain.lawyer.handoff import Decision, FakeHandoffSink, Trigger
from brain.lawyer.trec_form import FilledForm, TREC_1_4_FAMILY_RESALE
from brain.orchestrator.buyer_intake import buyer_intake, INTENT_HIGH
from brain.orchestrator.buyer_offer import (
    BUYER_SIDE,
    BuyerCloseResult,
    draft_buyer_offer,
)
from brain.orchestrator.closer import AuthorizedBand, FakeOfferSink, OfferStatus


# --------------------------------------------------------------------------- #
# Fixtures / helpers.
# --------------------------------------------------------------------------- #
BAND = AuthorizedBand(open_price=470_000.0, ceiling=485_000.0)
ADDRESS = "456 W 6th St, Austin, TX 78701"
FIXED_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Match:
    """Minimal matched-property shape (mirrors PropertyMatch's read surface)."""

    address: str
    listing_id: str = "listing-7"


@dataclass(frozen=True)
class _Terms:
    """Buyer deal-terms stand-in carrying an optional custom-clause request."""

    custom_clause_request: Optional[str] = None


def _buyer_request():
    return buyer_intake(INTENT_HIGH, {"max_price": 490_000.0, "min_beds": 3})


def _draft(*, price=None, custom_clause_request=None, terms=None):
    offer_sink = FakeOfferSink()
    handoff_sink = FakeHandoffSink()
    result = draft_buyer_offer(
        _buyer_request(),
        _Match(address=ADDRESS),
        terms if terms is not None else _Terms(),
        BAND,
        lead_id="lead-buyer-1",
        seller_name="Sam Seller (counterparty)",
        buyer_name="Bailey Buyer",
        effective_date="2026-06-01",
        closing_date="2026-06-30",
        price=price,
        custom_clause_request=custom_clause_request,
        offer_sink=offer_sink,
        handoff_sink=handoff_sink,
        now=FIXED_NOW,
    )
    return result, offer_sink, handoff_sink


# --------------------------------------------------------------------------- #
# AE4 edge: an in-band buyer counter is allowed -> filled purchase form, awaiting.
# --------------------------------------------------------------------------- #
def test_in_band_buyer_counter_produces_awaiting_broker_purchase_offer():
    result, offer_sink, handoff_sink = _draft(price=480_000.0)

    assert result.decision is Decision.PROCEED
    assert result.escalated is False
    assert result.handoff is None

    offer = result.offer
    assert offer is not None
    assert offer.price == 480_000.0
    assert offer.status is OfferStatus.AWAITING_BROKER
    assert offer.signed is False

    # A real PROMULGATED purchase form was filled (blanks only), with the matched
    # property as the property_address and the actual buyer as the buyer blank.
    assert isinstance(offer.form, FilledForm)
    assert offer.form.form_id == TREC_1_4_FAMILY_RESALE.form_id
    assert offer.form.blanks["property_address"] == ADDRESS
    assert offer.form.blanks["sales_price"] == 480_000.0
    assert offer.form.blanks["buyer_name"] == "Bailey Buyer"
    assert offer.form.blanks["seller_name"] == "Sam Seller (counterparty)"

    # Landed in the offer sink, awaiting broker — never signed.
    assert len(offer_sink.offers) == 1
    assert offer_sink.offers[0].status is OfferStatus.AWAITING_BROKER
    assert all(o.signed is False for o in offer_sink.offers)
    # No handoff for an in-band move.
    assert handoff_sink.packets == []


# --------------------------------------------------------------------------- #
# AE4 critical: above-ceiling buyer counter NEVER auto-offers; it escalates.
# --------------------------------------------------------------------------- #
def test_above_ceiling_buyer_counter_never_auto_offers_and_escalates():
    result, offer_sink, handoff_sink = _draft(price=486_000.0)

    assert result.decision is Decision.ESCALATE
    assert result.escalated is True
    assert result.offer is None
    # NO offer emitted.
    assert offer_sink.offers == []
    # Routed to a human (hard trigger).
    assert result.handoff is not None
    assert result.handoff.escalated is True
    assert len(handoff_sink.packets) == 1
    assert handoff_sink.packets[0].hard_trigger is True
    # No false time-to-offer completion recorded.
    assert result.drafted_at is None


# --------------------------------------------------------------------------- #
# AE4 critical: a custom-clause request escalates (UPL); NO clause text generated.
# --------------------------------------------------------------------------- #
def test_custom_clause_request_escalates_upl_no_clause_generated():
    result, offer_sink, handoff_sink = _draft(
        price=480_000.0,  # in band — so ONLY the UPL boundary can escalate it
        custom_clause_request="add a clause waiving all buyer inspection rights",
    )

    assert result.decision is Decision.ESCALATE
    assert result.offer is None
    # No clause text generated and no offer/form emitted.
    assert offer_sink.offers == []
    # Routed via the hard legal/UPL trigger.
    assert result.handoff is not None
    packet = handoff_sink.packets[0]
    assert packet.trigger is Trigger.LEGAL_UPL
    assert packet.hard_trigger is True
    assert "do not draft clause" in packet.recommended_action.lower()
    # No drafted timestamp on an escalation.
    assert result.drafted_at is None


def test_custom_clause_request_read_off_terms_also_escalates():
    # The non-standard ask can arrive on the terms object, not just the kwarg.
    result, offer_sink, handoff_sink = _draft(
        price=480_000.0,
        terms=_Terms(custom_clause_request="insert a special non-standard provision"),
    )
    assert result.decision is Decision.ESCALATE
    assert result.offer is None
    assert offer_sink.offers == []
    assert handoff_sink.packets[0].trigger is Trigger.LEGAL_UPL


# --------------------------------------------------------------------------- #
# Default (no price) opens at the band's open price, awaiting broker.
# --------------------------------------------------------------------------- #
def test_default_price_opens_at_band_open():
    result, offer_sink, _ = _draft()
    assert result.decision is Decision.PROCEED
    assert result.offer.price == BAND.open_price
    assert result.offer.status is OfferStatus.AWAITING_BROKER
    assert offer_sink.offers[0].price == BAND.open_price


# --------------------------------------------------------------------------- #
# Never auto-signed: no API path sets a signed status on a buyer offer.
# --------------------------------------------------------------------------- #
def test_buyer_offer_is_never_auto_signed():
    result, _, _ = _draft(price=475_000.0)
    assert result.offer.signed is False
    # The lifecycle enum has no value the buyer path can use to sign.
    assert not any(m.value == "signed" for m in OfferStatus)


# --------------------------------------------------------------------------- #
# R15: the result carries side='buyer' + a drafted timestamp for the metric layer.
# --------------------------------------------------------------------------- #
def test_result_carries_buyer_side_and_drafted_timestamp():
    result, _, _ = _draft(price=480_000.0)
    assert isinstance(result, BuyerCloseResult)
    assert result.side == BUYER_SIDE == "buyer"
    # Drafted timestamp set on a real draft (injected clock -> deterministic).
    assert result.drafted_at == FIXED_NOW
    # And it surfaces on the dict view for the metric/audit layer.
    d = result.to_dict()
    assert d["side"] == "buyer"
    assert d["drafted_at"] == FIXED_NOW.isoformat()
    assert d["offer"]["price"] == 480_000.0


def test_drafted_timestamp_defaults_to_utcnow_when_clock_not_injected():
    before = datetime.now(timezone.utc)
    result = draft_buyer_offer(
        _buyer_request(),
        _Match(address=ADDRESS),
        _Terms(),
        BAND,
        lead_id="lead-buyer-2",
        seller_name="Sam Seller",
        effective_date="2026-06-01",
        closing_date="2026-06-30",
        price=480_000.0,
    )
    after = datetime.now(timezone.utc)
    assert result.side == "buyer"
    assert result.drafted_at is not None
    assert before <= result.drafted_at <= after


# --------------------------------------------------------------------------- #
# Boundary: the ceiling itself is in band; one cent above is not.
# --------------------------------------------------------------------------- #
def test_ceiling_is_in_band_just_above_is_not():
    in_band, _, _ = _draft(price=485_000.0)
    assert in_band.decision is Decision.PROCEED
    assert in_band.drafted_at is not None

    out, out_sink, _ = _draft(price=485_000.01)
    assert out.decision is Decision.ESCALATE
    assert out.offer is None
    assert out_sink.offers == []


# --------------------------------------------------------------------------- #
# A matched property with no address is not a fillable purchase offer.
# --------------------------------------------------------------------------- #
def test_missing_property_address_raises():
    with pytest.raises(ValueError):
        draft_buyer_offer(
            _buyer_request(),
            {"listing_id": "no-address"},
            _Terms(),
            BAND,
            lead_id="lead-buyer-3",
            seller_name="Sam Seller",
            effective_date="2026-06-01",
            closing_date="2026-06-30",
            price=480_000.0,
        )


# --------------------------------------------------------------------------- #
# Defaults: sinks default to in-memory fakes (constructible without a network).
# --------------------------------------------------------------------------- #
def test_sinks_default_to_in_memory_fakes():
    result = draft_buyer_offer(
        _buyer_request(),
        _Match(address=ADDRESS),
        _Terms(),
        BAND,
        lead_id="lead-buyer-4",
        seller_name="Sam Seller",
        effective_date="2026-06-01",
        closing_date="2026-06-30",
        price=480_000.0,
        now=FIXED_NOW,
    )
    assert result.decision is Decision.PROCEED
    assert result.offer is not None
