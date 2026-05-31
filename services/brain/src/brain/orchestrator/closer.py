"""The Closer (U12) — seller cash-offer drafting under a licensed-broker gate.

This is the THIN transaction surface that sits on top of the deep Brain
(valuation) and Lawyer (handoff) pillars. Given a qualified
:class:`~brain.orchestrator.seller_intake.SellerRequest` and a
:class:`~brain.valuation.Valuation`, it drafts a cash *acquisition* offer:

1. Derives offer terms from the valuation, holding the opening price and any
   counter inside an AUTHORIZED BAND (``open_price`` .. ``ceiling``). The band is
   the negotiation guardrail (R9): a move at/below the ceiling is allowed; a move
   ABOVE the ceiling is NEVER auto-offered — it escalates to a human.
2. Fills a PROMULGATED TREC form (blanks only) via
   :func:`brain.lawyer.trec_form.fill_trec_form`. A request for a custom clause /
   non-standard term raises :class:`~brain.lawyer.trec_form.UplViolation`, which
   the Closer routes to a human — NO clause text is ever generated (the UPL
   boundary, KTD "autonomous up to a filled promulgated TREC form").
3. Routes out-of-band moves OR custom-clause / legal requests to
   :func:`brain.lawyer.handoff.decide` (the U8 hard-trigger entry point).
4. Emits the drafted offer to an injected :class:`OfferSink` in an
   ``"awaiting_broker"`` state — NEVER auto-signed. A licensed human broker signs
   at the Rails gate (U9).

The Closer never signs, never authors clause language, and never moves money. It
is deterministic and stdlib-only; the gRPC binding to Rails is a documented seam
(:class:`DomainOfferSink`), not built here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Protocol

from brain.lawyer.critic import ClaimVerdict, VerificationResult
from brain.lawyer.entailment import Label
from brain.lawyer.handoff import (
    Decision,
    HandoffDecision,
    HandoffSink,
    decide,
)
from brain.lawyer.trec_form import (
    FilledForm,
    TrecTerms,
    UplViolation,
    fill_trec_form,
)
from brain.orchestrator.seller_intake import SellerRequest
from brain.valuation import Valuation


# --------------------------------------------------------------------------- #
# Offer lifecycle + the authorized negotiation band.
# --------------------------------------------------------------------------- #
class OfferStatus(str, Enum):
    """Where a drafted offer sits. The MVP only ever emits ``AWAITING_BROKER``.

    There is intentionally NO ``signed`` value the Closer can set: signing is a
    licensed-human act at the Rails gate, structurally outside this module.
    """

    AWAITING_BROKER = "awaiting_broker"
    ESCALATED = "escalated"


# Default earnest money as a fraction of price for a cash acquisition offer (a
# ministerial, non-clause number — the form blank, not authored language).
DEFAULT_EARNEST_MONEY_RATE: float = 0.01


@dataclass(frozen=True)
class AuthorizedBand:
    """The negotiation guardrail (R9): open price up to a hard ceiling.

    ``open_price`` is the Closer's opening cash number; ``ceiling`` is the
    maximum a counter may reach WITHOUT human authorization. A price at/below the
    ceiling is in-band; ABOVE it is out-of-band and forces a handoff. The band is
    set by ops/broker policy, never by the model.
    """

    open_price: float
    ceiling: float

    def __post_init__(self) -> None:
        if self.open_price <= 0:
            raise ValueError("open_price must be positive")
        if self.ceiling < self.open_price:
            raise ValueError("ceiling must be >= open_price")

    def allows(self, price: float) -> bool:
        """True iff ``price`` is within the authorized band (at/below ceiling)."""
        return self.open_price <= price <= self.ceiling


def band_from_valuation(
    valuation: Valuation,
    *,
    open_discount: float = 0.90,
    ceiling_rate: float = 1.0,
) -> AuthorizedBand:
    """Derive an authorized band from a valuation (open below estimate, ceiling at it).

    A cash acquisition opens *below* the AVM estimate (``open_discount``) and is
    authorized up to ``ceiling_rate`` * estimate. Both knobs are ops policy. The
    valuation must have sufficient data — a no-data valuation cannot anchor a band.
    """
    if not valuation.sufficient_data or valuation.estimate <= 0:
        raise ValueError("cannot derive a band from a valuation without an estimate")
    open_price = round(valuation.estimate * open_discount, 2)
    ceiling = round(valuation.estimate * ceiling_rate, 2)
    return AuthorizedBand(open_price=open_price, ceiling=ceiling)


# --------------------------------------------------------------------------- #
# The drafted offer + sinks.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DraftedOffer:
    """A drafted cash offer awaiting a licensed broker's signature.

    ``lead_id`` ties it to the CRM lead. ``price`` is the offered cash amount
    (in-band by construction). ``form`` is the filled promulgated TREC form
    (blanks only). ``status`` is ALWAYS ``AWAITING_BROKER`` — never signed.
    ``band`` records the guardrail the price was checked against. ``side`` is
    "seller" (cash acquisition) or "buyer" (purchase offer).
    """

    lead_id: str
    price: float
    form: FilledForm
    band: AuthorizedBand
    status: OfferStatus = OfferStatus.AWAITING_BROKER
    side: str = "seller"

    @property
    def signed(self) -> bool:
        """Always False: the Closer never signs. Signing is a human Rails act."""
        return False

    def to_dict(self) -> dict:
        """Plain-dict view for the audit store / the Rails offer payload."""
        return {
            "lead_id": self.lead_id,
            "price": self.price,
            "side": self.side,
            "status": self.status.value,
            "signed": self.signed,
            "band": {"open_price": self.band.open_price, "ceiling": self.band.ceiling},
            "form": self.form.to_dict(),
        }


class OfferSink(Protocol):
    """Where a :class:`DraftedOffer` is emitted (injected, so tests use a fake).

    Implementations return an opaque offer id. The offer is ALWAYS handed over in
    ``awaiting_broker`` state; the sink must not sign it.
    """

    def emit(self, offer: DraftedOffer) -> str:  # pragma: no cover - protocol
        ...


@dataclass
class FakeOfferSink:
    """An in-memory sink that records drafted offers — for tests and dry runs.

    Performs NO network I/O. Inspect :attr:`offers` to assert what was drafted
    and that every recorded offer is ``awaiting_broker`` (never signed).
    """

    offers: List[DraftedOffer] = field(default_factory=list)

    def emit(self, offer: DraftedOffer) -> str:
        """Record ``offer`` (which must be awaiting-broker) and return an id."""
        assert offer.status is OfferStatus.AWAITING_BROKER, "offers are never auto-signed"
        self.offers.append(offer)
        return f"fake-offer-{len(self.offers)}"


class DomainOfferSink:
    """Emit drafted offers to Rails' awaiting-broker queue via ``Domain.CreateOffer``.

    Maps a :class:`DraftedOffer` to the proto ``CreateOfferRequest`` (lead_id,
    side, amount, property address, and the filled-form blanks/contingencies as
    JSON) and calls the Rails Domain gRPC service, which lands it in the Offer
    model's awaiting-broker-sign queue where a licensed broker reviews and signs.

    Mirrors :class:`brain.lawyer.handoff.DomainGrpcHandoffSink`: IMPORT-SAFE and
    connection-free at construction — the channel and stub are created LAZILY on
    the first :meth:`emit`, never at import or in ``__init__``. The default
    target is the Rails domain gRPC service (``domain-grpc:50052`` in compose).
    """

    def __init__(self, target: str = "localhost:50052") -> None:
        """Store the dial ``target`` only; do NOT open a channel here."""
        self._target = target
        self._channel = None  # lazily created grpc.Channel
        self._stub = None  # lazily created DomainStub

    def _ensure_stub(self):
        """Create the channel + stub on first use (lazy connect)."""
        if self._stub is None:
            import grpc  # imported lazily so importing this module needs no grpc

            from genproto.realestate.v1 import realestate_pb2_grpc

            self._channel = grpc.insecure_channel(self._target)
            self._stub = realestate_pb2_grpc.DomainStub(self._channel)
        return self._stub

    def emit(self, offer: DraftedOffer) -> str:
        """Map ``offer`` to the proto and call ``CreateOffer``; return the offer id.

        The Closer hands the offer over ``awaiting_broker`` and never signs;
        Rails enqueues it for a licensed broker. The filled-form blanks +
        selected contingencies travel as JSON in ``form_json``; the property
        address is read from the TREC form's blanks.
        """
        import json

        from genproto.realestate.v1 import realestate_pb2

        assert offer.status is OfferStatus.AWAITING_BROKER, "offers are never auto-signed"
        form = offer.form.to_dict()
        property_address = str(form.get("blanks", {}).get("property_address", ""))

        stub = self._ensure_stub()
        request = realestate_pb2.CreateOfferRequest(
            lead_id=offer.lead_id,
            side=offer.side,
            amount=offer.price,
            property_address=property_address,
            form_json=json.dumps(form),
        )
        return stub.CreateOffer(request).id


# --------------------------------------------------------------------------- #
# The result of a draft attempt.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CloseResult:
    """Outcome of :meth:`Closer.draft_offer` (loggable).

    Exactly one of ``offer`` / ``handoff`` is set:

    * ``offer`` present  -> an in-band offer was filled and emitted
      ``awaiting_broker`` (never signed).
    * ``handoff`` present -> the move was out-of-band, or a custom-clause / legal
      request tripped a hard trigger; routed to a human. NO offer emitted, NO
      clause text generated.
    """

    decision: Decision
    reason: str
    offer: Optional[DraftedOffer] = None
    handoff: Optional[HandoffDecision] = None

    @property
    def escalated(self) -> bool:
        """True iff the attempt was routed to a human instead of offering."""
        return self.decision is Decision.ESCALATE


# A trivially-grounded verification result so the Closer can reuse the U8
# ``decide`` entry point (which expects a VerificationResult). The Closer's own
# grounding is the valuation it was handed; this records that as a single cited,
# entailed claim so ``decide`` computes a high composite and only the HARD
# triggers (out-of-band -> high dollar, custom clause -> legal/UPL) can fire.
def _grounded_offer_result(valuation: Valuation, price: float) -> VerificationResult:
    """Wrap the offer's grounding as a VerificationResult for ``decide``."""
    citation = valuation.facts[0].source_id if valuation.facts else "valuation"
    verdict = ClaimVerdict(
        index=0,
        claim=f"Cash offer of {price} is anchored to a cited AVM valuation.",
        label=Label.ENTAILED,
        score=0.95,
        citation=citation,
        source_kind="valuation",
        reason="offer price anchored to the cited valuation",
    )
    return VerificationResult(
        approved=True,
        escalate=False,
        confidence=0.95,
        reason="offer anchored to cited valuation",
        claims=[verdict],
        approved_message=verdict.claim,
    )


@dataclass
class Closer:
    """Draft a cash acquisition offer under the band + UPL + broker gate.

    Injected with an :class:`OfferSink` (where in-band drafted offers land,
    awaiting broker sign) and a :class:`~brain.lawyer.handoff.HandoffSink` (where
    out-of-band / UPL escalations land). Both default to in-memory fakes so the
    Closer is constructible and testable without any network.
    """

    offer_sink: OfferSink
    handoff_sink: HandoffSink
    buyer_name: str = "Acme Home Buyers, LLC (licensed broker entity)"
    side: str = "seller"  # "seller" cash acquisition; "buyer" purchase offer

    def draft_offer(
        self,
        request: SellerRequest,
        valuation: Valuation,
        band: AuthorizedBand,
        *,
        lead_id: str,
        seller_name: str,
        effective_date: str,
        closing_date: str,
        price: Optional[float] = None,
        custom_clause_request: Optional[str] = None,
        transcript: str = "",
        completed_steps: Optional[List[str]] = None,
    ) -> CloseResult:
        """Draft (or escalate) a cash offer for ``request`` at ``valuation``.

        ``price`` defaults to the band's opening price; a counter is passed in as
        ``price``. ``custom_clause_request`` carries any non-standard ask the
        consumer made (detected and refused — UPL). The drafted in-band offer is
        emitted to the offer sink ``awaiting_broker``; an out-of-band price or a
        custom-clause request is routed to the handoff sink instead.

        Returns
        -------
        CloseResult
            ``offer`` set on success; ``handoff`` set on escalation. NEVER both.
        """
        offer_price = band.open_price if price is None else round(float(price), 2)
        steps = list(completed_steps or [])

        # --- UPL boundary: a custom-clause request never yields a form. ------ #
        # We try the fill FIRST so the typed UplViolation is the single source of
        # truth for the boundary; the form-fill refuses to author any clause.
        try:
            form = self._fill(
                request=request,
                price=offer_price,
                seller_name=seller_name,
                effective_date=effective_date,
                closing_date=closing_date,
                custom_clause_request=custom_clause_request,
            )
        except UplViolation as upl:
            # No clause text generated. Route to a human via the hard legal/UPL
            # trigger by handing ``decide`` text it detects as a clause request.
            handoff = decide(
                lead_id=lead_id,
                result=_grounded_offer_result(valuation, offer_price),
                fair_housing=None,
                text=f"Please add a custom clause: {upl.request}",
                sink=self.handoff_sink,
                transcript=transcript,
                amount=offer_price,
                completed_steps=steps,
                recommended_action=(
                    "Licensed broker/attorney to advise; do not draft clause "
                    "language. " + upl.reason
                ),
                # Keep the dollar band high so the LEGAL/UPL trigger is the
                # reported cause, not a high-dollar trip.
                high_dollar_band=float("inf"),
            )
            return CloseResult(
                decision=Decision.ESCALATE,
                reason=f"UPL escalation: {upl.reason}",
                handoff=handoff,
            )

        # --- Authorized band guardrail (R9). --------------------------------- #
        if not band.allows(offer_price):
            handoff = decide(
                lead_id=lead_id,
                result=_grounded_offer_result(valuation, offer_price),
                fair_housing=None,
                text="Confirm acceptance of this counter-offer amount.",
                sink=self.handoff_sink,
                transcript=transcript,
                amount=offer_price,
                completed_steps=steps,
                recommended_action=(
                    f"Counter {offer_price} exceeds authorized ceiling "
                    f"{band.ceiling}; broker to authorize before any offer."
                ),
                # The out-of-band amount IS the high-dollar binding-commitment
                # trip: route via the ceiling as the band so it always fires.
                high_dollar_band=round(band.ceiling + 0.01, 2),
            )
            return CloseResult(
                decision=Decision.ESCALATE,
                reason=(
                    f"out-of-band: counter {offer_price} exceeds ceiling "
                    f"{band.ceiling}; never auto-offered"
                ),
                handoff=handoff,
            )

        # --- In band + no clause request: emit awaiting-broker (never signed). #
        offer = DraftedOffer(
            lead_id=lead_id,
            price=offer_price,
            form=form,
            band=band,
            status=OfferStatus.AWAITING_BROKER,
            side=self.side,
        )
        self.offer_sink.emit(offer)
        return CloseResult(
            decision=Decision.PROCEED,
            reason=(
                f"in-band cash offer {offer_price} (open {band.open_price}, "
                f"ceiling {band.ceiling}) filled and queued awaiting broker sign"
            ),
            offer=offer,
        )

    def _fill(
        self,
        *,
        request: SellerRequest,
        price: float,
        seller_name: str,
        effective_date: str,
        closing_date: str,
        custom_clause_request: Optional[str],
    ) -> FilledForm:
        """Fill the promulgated TREC form from the offer terms (blanks only).

        Raises :class:`UplViolation` (propagated) if a custom clause was asked.
        """
        terms = TrecTerms(
            seller_name=seller_name,
            buyer_name=self.buyer_name,
            property_address=request.address,
            sales_price=price,
            earnest_money=round(price * DEFAULT_EARNEST_MONEY_RATE, 2),
            effective_date=effective_date,
            closing_date=closing_date,
            # A cash acquisition selects standard promulgated contingencies only
            # (no financing). These are ENUMERATED selections, not authored text.
            selected_contingencies=(),
            custom_clause_request=custom_clause_request,
        )
        return fill_trec_form(terms)


__all__ = [
    "OfferStatus",
    "AuthorizedBand",
    "band_from_valuation",
    "DraftedOffer",
    "OfferSink",
    "FakeOfferSink",
    "DomainOfferSink",
    "CloseResult",
    "Closer",
    "DEFAULT_EARNEST_MONEY_RATE",
]
