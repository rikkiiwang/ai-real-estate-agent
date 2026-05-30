"""U12 tests — seller cash-offer + broker gate (thin Closer), stdlib only.

Covers AE4 / R8 / R9. Test-first on the two load-bearing guardrails (the plan's
execution note): the AUTHORIZED-BAND guardrail and the UPL escalation boundary.

Band fixture {open 470000, ceiling 485000}:

* a counter at 480000 (in band) IS allowed -> a filled TREC form lands in the
  offer sink in ``awaiting_broker`` state, never signed;
* a counter at 486000 (above ceiling) NEVER auto-offers -> it escalates and NO
  offer is emitted;
* a request for a custom clause escalates (UPL) and NO clause text is generated
  (the form-fill refuses; the offer sink stays empty);
* every emitted offer is ``awaiting_broker`` and ``signed`` is always False.

No network: the Closer is exercised with in-memory fakes only.
"""
from __future__ import annotations

import pytest

from brain.lawyer.handoff import Decision, FakeHandoffSink, Trigger
from brain.lawyer.trec_form import (
    CASH_OFFER_CONTINGENCIES,
    Contingency,
    FilledForm,
    TREC_1_4_FAMILY_RESALE,
    TrecTerms,
    UplViolation,
    fill_trec_form,
)
from brain.orchestrator.closer import (
    AuthorizedBand,
    Closer,
    DomainOfferSink,
    FakeOfferSink,
    OfferStatus,
    band_from_valuation,
)
from brain.orchestrator.seller_intake import seller_intake, INTENT_HIGH
from brain.valuation import Fact, Valuation


# --------------------------------------------------------------------------- #
# Fixtures / helpers.
# --------------------------------------------------------------------------- #
BAND = AuthorizedBand(open_price=470_000.0, ceiling=485_000.0)
ADDRESS = "123 Congress Ave, Austin, TX 78701"


def _valuation() -> Valuation:
    return Valuation(
        sufficient_data=True,
        estimate=485_000.0,
        low=460_000.0,
        high=505_000.0,
        facts=[Fact(source_id="tcad-001", kind="feature:sqft", description="sqft")],
    )


def _request():
    return seller_intake(ADDRESS, INTENT_HIGH, {"timeline": "30 days"})


def _closer():
    return Closer(offer_sink=FakeOfferSink(), handoff_sink=FakeHandoffSink())


def _draft(closer: Closer, *, price=None, custom_clause_request=None):
    return closer.draft_offer(
        _request(),
        _valuation(),
        BAND,
        lead_id="lead-closer-1",
        seller_name="Pat Seller",
        effective_date="2026-06-01",
        closing_date="2026-06-30",
        price=price,
        custom_clause_request=custom_clause_request,
    )


# --------------------------------------------------------------------------- #
# trec_form unit — blanks only, enumerated options, UPL boundary.
# --------------------------------------------------------------------------- #
def _terms(**over):
    base = dict(
        seller_name="Pat Seller",
        buyer_name="Acme Home Buyers, LLC",
        property_address=ADDRESS,
        sales_price=480_000.0,
        earnest_money=4_800.0,
        effective_date="2026-06-01",
        closing_date="2026-06-30",
    )
    base.update(over)
    return TrecTerms(**base)


def test_fill_populates_factual_blanks_only():
    form = fill_trec_form(_terms())
    assert isinstance(form, FilledForm)
    assert form.form_id == TREC_1_4_FAMILY_RESALE.form_id
    # Every promulgated factual blank is filled with a fact (string/number).
    for blank in TREC_1_4_FAMILY_RESALE.factual_blanks:
        assert blank in form.blanks
    assert form.blanks["sales_price"] == 480_000.0
    assert form.blanks["property_address"] == ADDRESS
    # No free-text clause field exists on the dataclass at all (structural).
    assert "clause" not in form.to_dict()


def test_fill_selects_only_enumerated_contingencies():
    form = fill_trec_form(_terms(selected_contingencies=(Contingency.INSPECTION,)))
    assert form.selected_contingencies == (Contingency.INSPECTION,)
    assert Contingency.INSPECTION in CASH_OFFER_CONTINGENCIES


def test_fill_refuses_custom_clause_request_upl():
    with pytest.raises(UplViolation):
        fill_trec_form(_terms(custom_clause_request="waive all seller liability forever"))


def test_fill_rejects_bad_factual_blank():
    with pytest.raises(ValueError):
        fill_trec_form(_terms(sales_price=0))


def test_band_from_valuation():
    band = band_from_valuation(_valuation())
    assert band.open_price < band.ceiling
    assert band.ceiling == 485_000.0


# --------------------------------------------------------------------------- #
# AE4 edge: a counter WITHIN the band is allowed -> filled form, awaiting broker.
# --------------------------------------------------------------------------- #
def test_in_band_counter_produces_awaiting_broker_offer():
    closer = _closer()
    result = _draft(closer, price=480_000.0)
    assert result.decision is Decision.PROCEED
    assert result.escalated is False
    assert result.handoff is None

    offer = result.offer
    assert offer is not None
    assert offer.price == 480_000.0
    assert offer.status is OfferStatus.AWAITING_BROKER
    assert offer.signed is False
    # A real promulgated form was filled (blanks only).
    assert isinstance(offer.form, FilledForm)
    assert offer.form.blanks["sales_price"] == 480_000.0

    # It landed in the offer sink, awaiting broker — never signed.
    assert len(closer.offer_sink.offers) == 1
    assert closer.offer_sink.offers[0].status is OfferStatus.AWAITING_BROKER
    assert all(o.signed is False for o in closer.offer_sink.offers)
    # No handoff for an in-band move.
    assert closer.handoff_sink.packets == []


# --------------------------------------------------------------------------- #
# AE4 critical: a counter ABOVE the ceiling NEVER auto-offers; it escalates.
# --------------------------------------------------------------------------- #
def test_above_ceiling_counter_never_auto_offers_and_escalates():
    closer = _closer()
    result = _draft(closer, price=486_000.0)
    assert result.decision is Decision.ESCALATE
    assert result.escalated is True
    assert result.offer is None
    # NO offer was emitted.
    assert closer.offer_sink.offers == []
    # It was routed to a human.
    assert result.handoff is not None
    assert result.handoff.escalated is True
    assert len(closer.handoff_sink.packets) == 1
    assert closer.handoff_sink.packets[0].hard_trigger is True


# --------------------------------------------------------------------------- #
# AE4 critical: a custom-clause request escalates (UPL); NO clause text generated.
# --------------------------------------------------------------------------- #
def test_custom_clause_request_escalates_upl_no_clause_generated():
    closer = _closer()
    result = _draft(
        closer,
        price=480_000.0,  # in band — so ONLY the UPL boundary can escalate it
        custom_clause_request="add a clause indemnifying the buyer against all defects",
    )
    assert result.decision is Decision.ESCALATE
    assert result.offer is None
    # No clause text was generated and no offer/form emitted.
    assert closer.offer_sink.offers == []
    # Routed via the hard legal/UPL trigger.
    assert result.handoff is not None
    packet = closer.handoff_sink.packets[0]
    assert packet.trigger is Trigger.LEGAL_UPL
    assert packet.hard_trigger is True
    # The recommended action explicitly forbids drafting clause language.
    assert "do not draft clause" in packet.recommended_action.lower()


# --------------------------------------------------------------------------- #
# Default (no price) opens at the band's open price, awaiting broker.
# --------------------------------------------------------------------------- #
def test_default_price_opens_at_band_open():
    closer = _closer()
    result = _draft(closer)
    assert result.decision is Decision.PROCEED
    assert result.offer.price == BAND.open_price
    assert result.offer.status is OfferStatus.AWAITING_BROKER


# --------------------------------------------------------------------------- #
# An offer is NEVER auto-signed: no API path sets a signed status.
# --------------------------------------------------------------------------- #
def test_offer_is_never_auto_signed():
    closer = _closer()
    result = _draft(closer, price=475_000.0)
    assert result.offer.signed is False
    assert OfferStatus.AWAITING_BROKER.value == "awaiting_broker"
    # The lifecycle enum has no value the Closer can use to sign.
    assert not any(m.value == "signed" for m in OfferStatus)


# --------------------------------------------------------------------------- #
# Boundary values: the ceiling itself is in band; one cent above is not.
# --------------------------------------------------------------------------- #
def test_ceiling_is_in_band_just_above_is_not():
    in_band = _draft(_closer(), price=485_000.0)
    assert in_band.decision is Decision.PROCEED
    out = _draft(_closer(), price=485_000.01)
    assert out.decision is Decision.ESCALATE
    assert out.offer is None


# --------------------------------------------------------------------------- #
# DomainOfferSink seam — import-safe, connection-free, unbound (documented).
# --------------------------------------------------------------------------- #
def test_domain_offer_sink_constructs_without_connecting():
    sink = DomainOfferSink(target="localhost:50051")
    assert sink._channel is None
    assert sink._stub is None


def test_domain_offer_sink_emit_is_an_explicit_unbound_seam():
    closer = _closer()
    result = _draft(closer, price=480_000.0)
    sink = DomainOfferSink()
    with pytest.raises(NotImplementedError):
        sink.emit(result.offer)
