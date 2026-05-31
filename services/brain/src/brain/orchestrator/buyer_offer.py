"""Buyer purchase-offer draft + broker gate (U15) — the BUYER side of the Closer.

U12 built the seller-side :class:`~brain.orchestrator.closer.Closer`: it fills a
PROMULGATED TREC form (blanks only — no clause authoring, the UPL line), enforces
the :class:`~brain.orchestrator.closer.AuthorizedBand` negotiation guardrail (R9),
routes out-of-band moves / custom-clause / legal requests to the human via
``lawyer.handoff.decide``, and emits the drafted offer to an injected
:class:`~brain.orchestrator.closer.OfferSink` in ``AWAITING_BROKER`` state — NEVER
auto-signed.

U15 is the *same discipline* on the BUYER side: a buyer makes a TREC One-to-Four
Family resale PURCHASE offer on a matched property. The compliance shape is
identical, only the party roles flip — so this module does NOT re-implement the
guardrail. It **reuses the Closer**:

* The Closer is seller-shaped: it takes a subject ``request`` carrying the
  property ``.address``, treats the configured broker entity as the *buyer*, and
  fills ``seller_name`` from a blank. On the buyer side the human consumer IS the
  buyer and the listing's seller is the counterparty. We adapt — without forking
  the guardrail — by:
    1. handing the Closer a thin duck-typed subject (:class:`_PropertySubject`)
       that exposes ``.address`` (the matched property), exactly the one field
       ``Closer.draft_offer`` reads off the request;
    2. setting the Closer's ``buyer_name`` to the actual buyer and passing the
       counterparty seller through the existing ``seller_name`` blank;
    3. delegating to :meth:`Closer.draft_offer` so the band check, the UPL
       form-fill boundary, the handoff routing, and the awaiting-broker emission
       are the *one* implementation in :mod:`brain.orchestrator.closer`.

* The result is wrapped as a :class:`BuyerCloseResult` that carries ``side =
  "buyer"`` and the ``drafted_at`` timestamp, so the time-to-offer metric layer
  (R15, owner of ``metrics.py``) can extend to the buyer variant by reading the
  side + timestamp off the returned offer — WITHOUT this module importing the
  metrics module.

Nothing here authors clause language, signs, or moves money — those properties
hold by construction because all of that lives in the reused Closer/trec_form
machinery, which this module never modifies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from brain.lawyer.handoff import Decision, HandoffDecision, HandoffSink
from brain.orchestrator.buyer_intake import BuyerRequest
from brain.orchestrator.closer import (
    AuthorizedBand,
    Closer,
    CloseResult,
    DraftedOffer,
    FakeOfferSink,
    OfferSink,
)

# The transaction side this module drafts for. The seller side ("seller") lives
# in the Closer's own ``draft_offer``; this is the buyer counterpart, surfaced on
# the result so the metric layer can key time-to-offer by variant (R15).
BUYER_SIDE = "buyer"

# Default buyer-entity name when the caller does not supply one. The licensed
# broker entity represents the buyer at the gate; the human broker signs (U9).
DEFAULT_BUYER_NAME = "Represented Buyer (under licensed broker entity)"


@dataclass(frozen=True)
class _PropertySubject:
    """Thin duck-typed subject the seller-shaped Closer reads ``.address`` off.

    :meth:`Closer.draft_offer` only ever reads ``request.address`` (to fill the
    promulgated form's ``property_address`` blank). Rather than fork the Closer to
    accept a :class:`~brain.orchestrator.buyer_intake.BuyerRequest` (which has no
    single subject address — matching yields candidates), we hand it this minimal
    subject carrying the matched property's address. This is the adapter seam that
    lets the BUYER flow reuse the seller-shaped guardrail unchanged.
    """

    address: str


@dataclass(frozen=True)
class BuyerCloseResult:
    """A buyer-side draft outcome — the Closer's result + buyer metric metadata.

    Wraps the reused :class:`~brain.orchestrator.closer.CloseResult` (which holds
    the in-band ``offer`` OR the ``handoff``, never both) and adds the two fields
    the time-to-offer metric layer (R15) needs to extend to the buyer variant:

    * ``side`` — always :data:`BUYER_SIDE`, so a metric keyed by variant can tell
      buyer drafts from seller drafts.
    * ``drafted_at`` — the UTC timestamp the buyer offer was drafted. Set ONLY
      when an offer was actually produced (an escalation drafts no offer, so it
      records no false completion — mirrors the seller-side metric contract).

    This module deliberately does NOT import the metrics module; it just exposes
    the side + timestamp on the result so the metric layer can consume them.
    """

    result: CloseResult
    side: str = BUYER_SIDE
    drafted_at: Optional[datetime] = None

    # --- pass-throughs so callers treat this like a CloseResult --------------- #
    @property
    def decision(self) -> Decision:
        """The routing decision (proceed | escalate) from the reused Closer."""
        return self.result.decision

    @property
    def reason(self) -> str:
        """The Closer's human-readable audit reason."""
        return self.result.reason

    @property
    def offer(self) -> Optional[DraftedOffer]:
        """The drafted buyer offer (awaiting broker) — ``None`` on escalation."""
        return self.result.offer

    @property
    def handoff(self) -> Optional[HandoffDecision]:
        """The escalation decision — ``None`` when an offer was drafted."""
        return self.result.handoff

    @property
    def escalated(self) -> bool:
        """True iff routed to a human instead of drafting an offer."""
        return self.result.escalated

    def to_dict(self) -> dict:
        """Plain-dict view including the buyer-variant metric metadata."""
        return {
            "side": self.side,
            "decision": self.result.decision.value,
            "reason": self.result.reason,
            "drafted_at": self.drafted_at.isoformat() if self.drafted_at else None,
            "offer": self.result.offer.to_dict() if self.result.offer else None,
        }


def draft_buyer_offer(
    buyer_request: BuyerRequest,
    matched_property: object,
    terms: object,
    band: AuthorizedBand,
    *,
    lead_id: str,
    seller_name: str,
    effective_date: str,
    closing_date: str,
    offer_sink: Optional[OfferSink] = None,
    handoff_sink: Optional[HandoffSink] = None,
    buyer_name: str = DEFAULT_BUYER_NAME,
    price: Optional[float] = None,
    custom_clause_request: Optional[str] = None,
    transcript: str = "",
    completed_steps: Optional[List[str]] = None,
    now: Optional[datetime] = None,
) -> BuyerCloseResult:
    """Draft (or escalate) a BUYER TREC purchase offer on a matched property.

    Reuses the seller-side :class:`~brain.orchestrator.closer.Closer` for ALL of
    the compliance logic — the authorized-band guardrail (R9), the UPL form-fill
    boundary (custom clause -> :class:`UplViolation` -> handoff, no clause text),
    the handoff routing, and the awaiting-broker emission. This function only
    adapts the party roles to the buyer side and records the buyer-variant
    offer-drafted timestamp/side for the metric layer (R15).

    Parameters
    ----------
    buyer_request:
        The structured :class:`~brain.orchestrator.buyer_intake.BuyerRequest`. Its
        intent/criteria already passed equal-service qualification (U14); the
        offer draft itself is neutral.
    matched_property:
        The property the buyer is offering on — a mapping or object carrying an
        ``address`` (the U14 :class:`~brain.orchestrator.matching.PropertyMatch`
        shape works directly). Its address fills the promulgated form's
        ``property_address`` blank.
    terms:
        The deal-terms object (carries an optional ``custom_clause_request`` the
        consumer made). Accepted for parity with the seller call shape; the
        explicit keyword args take precedence when given. A custom-clause request
        on ``terms`` is detected and refused (UPL) exactly as on the seller side.
    band:
        The :class:`~brain.orchestrator.closer.AuthorizedBand` negotiation
        guardrail. A buyer counter at/below the ceiling is in band; above it
        NEVER auto-offers and escalates.
    lead_id, seller_name, effective_date, closing_date:
        Factual form blanks. ``seller_name`` is the COUNTERPARTY (the listing
        seller) on the buyer side; ``buyer_name`` (below) is the consumer.
    offer_sink, handoff_sink:
        Injected sinks (default to in-memory fakes so this is constructible and
        testable without any network). In-band offers land in ``offer_sink``
        ``awaiting_broker``; escalations land in ``handoff_sink``.
    buyer_name:
        The buyer the offer is made on behalf of (the consumer / their broker
        entity). Flipped into the Closer's ``buyer_name`` so the promulgated
        form's buyer blank carries the actual buyer.
    price:
        The buyer's offered price; defaults to the band's opening price.
    custom_clause_request:
        Any non-standard ask the consumer made — detected and refused (UPL); NO
        clause text is ever generated. Falls back to ``terms.custom_clause_request``
        when not given explicitly.
    now:
        Injectable clock for the drafted timestamp (defaults to ``utcnow``), so
        the metric layer's time-to-offer is deterministic in tests.

    Returns
    -------
    BuyerCloseResult
        Carries the reused Closer's :class:`CloseResult` plus ``side="buyer"`` and
        a ``drafted_at`` timestamp (set ONLY when an offer was drafted). An
        escalation records no timestamp — no false completion for the metric.
    """
    sinks_offer = offer_sink if offer_sink is not None else FakeOfferSink()
    sinks_handoff = handoff_sink if handoff_sink is not None else _default_handoff_sink()

    # Resolve the custom-clause ask: explicit arg wins, else read it off `terms`
    # if present. (The Closer/trec_form layer does the actual UPL refusal.)
    clause = custom_clause_request
    if clause is None:
        clause = getattr(terms, "custom_clause_request", None)

    subject = _PropertySubject(address=_address_of(matched_property))

    # Reuse the seller-shaped Closer, with the BUYER as `buyer_name` and the
    # listing seller passed through the existing `seller_name` blank. All band /
    # UPL / handoff / awaiting-broker logic is the Closer's single implementation.
    closer = Closer(
        offer_sink=sinks_offer,
        handoff_sink=sinks_handoff,
        buyer_name=buyer_name,
        side="buyer",
    )
    result: CloseResult = closer.draft_offer(
        subject,  # duck-typed: Closer only reads `.address`
        _terms_valuation(terms),
        band,
        lead_id=lead_id,
        seller_name=seller_name,
        effective_date=effective_date,
        closing_date=closing_date,
        price=price,
        custom_clause_request=clause,
        transcript=transcript,
        completed_steps=completed_steps,
    )

    # Record the buyer-variant offer-drafted timestamp ONLY on a real draft, so an
    # escalation never looks like a completed time-to-offer (R15 honesty).
    drafted_at = None
    if result.decision is Decision.PROCEED and result.offer is not None:
        drafted_at = (now or datetime.now(timezone.utc))

    return BuyerCloseResult(result=result, side=BUYER_SIDE, drafted_at=drafted_at)


def _address_of(matched_property: object) -> str:
    """Read the property ``address`` off a mapping or an object (matching shape).

    Accepts the U14 :class:`~brain.orchestrator.matching.PropertyMatch` (an object
    with ``.address``) or a plain mapping. Raises if no address is present — a
    purchase offer with no subject property is not a fillable promulgated form.
    """
    if isinstance(matched_property, str):
        address = matched_property
    elif isinstance(matched_property, dict):
        address = matched_property.get("address")
    else:
        address = getattr(matched_property, "address", None)
    if not address or not str(address).strip():
        raise ValueError(
            "draft_buyer_offer requires a matched property with an address "
            "(the promulgated form's property_address blank)"
        )
    return str(address)


def _terms_valuation(terms: object) -> object:
    """Resolve the grounding valuation the Closer anchors the offer to.

    The Closer wraps a valuation as the offer's grounding for ``handoff.decide``
    (so only the HARD triggers — out-of-band / UPL — fire). A buyer's terms may
    carry the matched property's ``valuation``; if absent, the Closer tolerates a
    valuation with no ``facts`` (it falls back to a ``"valuation"`` citation), so
    a minimal stand-in keeps the buyer path working without a full AVM run.
    """
    valuation = getattr(terms, "valuation", None)
    if valuation is not None:
        return valuation
    return _StandInValuation()


@dataclass(frozen=True)
class _StandInValuation:
    """A minimal grounding stand-in when terms carry no valuation.

    Mirrors the few attributes ``Closer`` reads off a valuation (``facts`` for the
    citation). It is only used to anchor the handoff's grounded result; the offer
    price itself comes from the authorized band, not this object.
    """

    facts: tuple = ()


def _default_handoff_sink() -> HandoffSink:
    """In-memory handoff sink default (kept here to avoid a top-level import)."""
    from brain.lawyer.handoff import FakeHandoffSink

    return FakeHandoffSink()


__all__ = [
    "BUYER_SIDE",
    "DEFAULT_BUYER_NAME",
    "BuyerCloseResult",
    "draft_buyer_offer",
]
