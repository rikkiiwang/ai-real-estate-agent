"""One-property acquire->list->resell loop (U16) — the demo spine.

This is the demonstration spine for R14: a SINGLE property moves through the
shared core, acquired on the SELLER side and resold on the BUYER side, proving
the seller and buyer flows share one Brain + offer engine. It adds NO new agent
logic — it is pure orchestration over the already-built units:

* the seller acquisition draft reuses :class:`~brain.orchestrator.closer.Closer`
  (via a :class:`~brain.orchestrator.seller_intake.SellerRequest`);
* the buyer side reuses :func:`~brain.orchestrator.matching.match_properties`
  to (re)discover the same property and
  :func:`~brain.orchestrator.buyer_offer.draft_buyer_offer` to draft the resale
  purchase offer.

The Property lifecycle (system-of-record seam)
----------------------------------------------
The Rails domain (``services/domain`` — ``app/models/property.rb``) is the
SYSTEM OF RECORD for a Property and owns the canonical lifecycle
``acquired -> listed -> under_offer -> sold`` with a guarded
``Property::IllegalTransition`` on any illegal move. This module does NOT touch
Rails; it MIRRORS that lifecycle on the Python side so the demo spine can run
hermetically (injected clocks/sinks/fakes, stdlib only), and raises a typed
:class:`IllegalTransition` that mirrors the Rails intent. The Python
:class:`PropertyState` machine is the in-process projection; the Rails model is
authoritative once wired over gRPC (a documented follow-up, not built here).

The transition guard is intentionally strict (mirrors Rails):

* cannot ``list`` before ``acquired``;
* cannot move ``under_offer`` before ``listed``;
* cannot ``sell`` before ``under_offer``;
* no backward moves and no skipped states.

Determinism
-----------
The loop is hermetic: every side effect is injected (offer sinks, handoff
sinks, and the drafted-at clock). With the same inputs it produces the same
final state and the same drafted offers — there is no network and no wall-clock
dependence beyond the injectable ``now``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Mapping, Optional

from brain.lawyer.critic import Critic
from brain.lawyer.handoff import FakeHandoffSink, HandoffSink
from brain.orchestrator.buyer_intake import BuyerRequest
from brain.orchestrator.buyer_offer import (
    BuyerCloseResult,
    DEFAULT_BUYER_NAME,
    draft_buyer_offer,
)
from brain.orchestrator.closer import (
    AuthorizedBand,
    CloseResult,
    Closer,
    FakeOfferSink,
    OfferSink,
)
from brain.orchestrator.matching import PropertyMatch, match_properties
from brain.orchestrator.seller_intake import SellerRequest
from brain.valuation import Valuation


# --------------------------------------------------------------------------- #
# Property lifecycle — mirrors the Rails Property model (system of record).
# --------------------------------------------------------------------------- #
class PropertyStatus(str, Enum):
    """The Property lifecycle states (mirror of the Rails ``Property`` enum).

    The canonical order is ``ACQUIRED -> LISTED -> UNDER_OFFER -> SOLD``. Rails
    (``app/models/property.rb``) is the system of record; this enum is the
    in-process projection the demo spine drives.
    """

    ACQUIRED = "acquired"
    LISTED = "listed"
    UNDER_OFFER = "under_offer"
    SOLD = "sold"


# The single legal forward path. A property enters at ACQUIRED (the seller flow
# acquired it); every subsequent move must be the immediate next state — no
# skips, no backward moves. Mirrors the Rails state-machine transition table.
_NEXT_STATUS: Mapping[PropertyStatus, PropertyStatus] = {
    PropertyStatus.ACQUIRED: PropertyStatus.LISTED,
    PropertyStatus.LISTED: PropertyStatus.UNDER_OFFER,
    PropertyStatus.UNDER_OFFER: PropertyStatus.SOLD,
}


class IllegalTransition(Exception):
    """Raised on an illegal Property lifecycle transition.

    Mirrors the intent of the Rails ``Property::IllegalTransition``: the guard
    refuses any move that is not the single legal forward step (cannot list
    before acquired, cannot sell before under_offer, no backward/skip moves).
    """

    def __init__(self, current: PropertyStatus, target: PropertyStatus) -> None:
        self.current = current
        self.target = target
        nxt = _NEXT_STATUS.get(current)
        allowed = nxt.value if nxt is not None else "(terminal: no further moves)"
        super().__init__(
            f"illegal Property transition {current.value} -> {target.value}: "
            f"only {current.value} -> {allowed} is allowed"
        )


@dataclass
class PropertyState:
    """A single property's identity + guarded lifecycle position.

    Mirrors the Rails ``Property`` row the demo spine drives: a stable
    ``property_id``/``address`` identity and a ``status`` that may only advance
    one legal step at a time. ``history`` records the states visited (audit
    trail), so the same property identity can be asserted to flow through both
    the seller and buyer sides.

    The property ENTERS at :attr:`PropertyStatus.ACQUIRED` — the seller flow is
    what acquires it (a drafted acquisition offer), so a constructed
    ``PropertyState`` represents an already-acquired property. ``list_()``,
    ``mark_under_offer()`` and ``sell()`` are the guarded forward transitions.
    """

    property_id: str
    address: str
    status: PropertyStatus = PropertyStatus.ACQUIRED
    history: List[PropertyStatus] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.property_id or not str(self.property_id).strip():
            raise ValueError("PropertyState requires a non-empty property_id")
        if not self.address or not str(self.address).strip():
            raise ValueError("PropertyState requires a non-empty address")
        # Seed history with the entry state so the audit trail is complete.
        if not self.history:
            self.history = [self.status]

    # --- the single guarded transition primitive --------------------------- #
    def _advance_to(self, target: PropertyStatus) -> None:
        """Advance to ``target`` iff it is the one legal next state, else raise."""
        if _NEXT_STATUS.get(self.status) is not target:
            raise IllegalTransition(self.status, target)
        self.status = target
        self.history.append(target)

    # --- named transitions (read like the Rails state-machine events) ------ #
    def list_(self) -> None:
        """ACQUIRED -> LISTED. Raises if not currently acquired."""
        self._advance_to(PropertyStatus.LISTED)

    def mark_under_offer(self) -> None:
        """LISTED -> UNDER_OFFER. Raises if not currently listed."""
        self._advance_to(PropertyStatus.UNDER_OFFER)

    def sell(self) -> None:
        """UNDER_OFFER -> SOLD. Raises if not currently under offer."""
        self._advance_to(PropertyStatus.SOLD)

    # --- convenience predicates -------------------------------------------- #
    @property
    def is_listed(self) -> bool:
        """True once the property has been listed (available to the buyer flow)."""
        return self.status in (
            PropertyStatus.LISTED,
            PropertyStatus.UNDER_OFFER,
            PropertyStatus.SOLD,
        )

    @property
    def is_sold(self) -> bool:
        """True once the resale closed."""
        return self.status is PropertyStatus.SOLD

    def to_dict(self) -> dict:
        """Plain-dict view (mirrors the Rails Property row the spine projects)."""
        return {
            "property_id": self.property_id,
            "address": self.address,
            "status": self.status.value,
            "history": [s.value for s in self.history],
        }


# --------------------------------------------------------------------------- #
# The loop result — a loggable record of one property's end-to-end run.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LoopResult:
    """Outcome of one acquire->list->resell run on a single property.

    Carries the same property identity that flowed through both sides plus the
    two drafted outcomes:

    * ``property_state`` — the final lifecycle position (``sold`` on a happy run).
    * ``acquisition`` — the seller-side acquisition draft (the Closer's
      :class:`~brain.orchestrator.closer.CloseResult`).
    * ``resale`` — the buyer-side resale purchase draft
      (:class:`~brain.orchestrator.buyer_offer.BuyerCloseResult`).
    * ``match`` — the :class:`~brain.orchestrator.matching.PropertyMatch` the
      buyer flow re-discovered the SAME property as (proves the identity flows
      across both sides).
    """

    property_state: PropertyState
    acquisition: CloseResult
    resale: BuyerCloseResult
    match: PropertyMatch

    @property
    def sold(self) -> bool:
        """True iff the property completed the full loop and reached ``sold``."""
        return self.property_state.is_sold

    def to_dict(self) -> dict:
        """Plain-dict view for logging / the demo report."""
        return {
            "property": self.property_state.to_dict(),
            "acquisition": {
                "decision": self.acquisition.decision.value,
                "reason": self.acquisition.reason,
                "offer": (
                    self.acquisition.offer.to_dict()
                    if self.acquisition.offer
                    else None
                ),
            },
            "resale": self.resale.to_dict(),
            "matched_address": self.match.address,
            "matched_listing_id": self.match.listing_id,
        }


# --------------------------------------------------------------------------- #
# The loop driver.
# --------------------------------------------------------------------------- #
@dataclass
class PropertyLoop:
    """Drive ONE property end-to-end through the shared core (acquire->resell).

    Injected with everything the run touches so it is hermetic and deterministic:

    * ``offer_sink`` / ``handoff_sink`` — where drafted offers and escalations
      land (default in-memory fakes; no network).
    * ``now`` — the drafted-at clock the buyer offer stamps (default ``utcnow``);
      pin it in tests for determinism.

    The driver REUSES the existing components and adds no agent logic:

    1. SELLER side acquires the property — :meth:`Closer.draft_offer` fills the
       acquisition TREC form awaiting broker; the property enters ``acquired``.
    2. It is ``listed`` (a guarded transition).
    3. BUYER side re-discovers the SAME property via
       :func:`match_properties` and drafts the resale purchase offer via
       :func:`draft_buyer_offer`; the property moves ``under_offer`` then
       ``sold``.
    """

    offer_sink: OfferSink = field(default_factory=FakeOfferSink)
    handoff_sink: HandoffSink = field(default_factory=FakeHandoffSink)
    now: Optional[datetime] = None

    def run_loop(
        self,
        *,
        property_id: str,
        seller_request: SellerRequest,
        seller_valuation: Valuation,
        acquisition_band: AuthorizedBand,
        buyer_request: BuyerRequest,
        resale_band: AuthorizedBand,
        resale_terms: object,
        lead_id: str,
        seller_name: str,
        buyer_name_acquisition: str = "Acme Home Buyers, LLC (licensed broker entity)",
        buyer_name_resale: str = DEFAULT_BUYER_NAME,
        resale_seller_name: Optional[str] = None,
        effective_date: str = "2026-06-01",
        closing_date: str = "2026-06-30",
        listing_extras: Optional[Mapping[str, Any]] = None,
        critic: Optional[Critic] = None,
        acquisition_price: Optional[float] = None,
        resale_price: Optional[float] = None,
    ) -> LoopResult:
        """Run one property end-to-end through the seller then buyer flow.

        Parameters
        ----------
        property_id:
            Stable identity for the property (mirrors the Rails Property id /
            the buyer-side ``listing_id``). It is the SAME id used on both
            sides, which is how the demo proves one property crosses the seam.
        seller_request:
            The qualified :class:`SellerRequest` whose ``address`` is the subject
            property. Its address is the canonical address carried through.
        seller_valuation:
            The grounding :class:`Valuation` the acquisition offer anchors to.
        acquisition_band / resale_band:
            The authorized negotiation bands (R9) for each side.
        buyer_request:
            The qualified :class:`BuyerRequest` whose neutral criteria the buyer
            flow matches the listed property against.
        resale_terms:
            The buyer deal-terms object handed to :func:`draft_buyer_offer`.
        listing_extras:
            Optional extra NEUTRAL candidate fields (beds/baths/price/sqft/
            location/property_type and optional ``valuation``/``photo_findings``)
            used when the listed property is presented to the buyer matcher, so
            the buyer's criteria actually match. The property's ``listing_id``
            and ``address`` are always set from this run's identity.
        critic:
            Optional injected Critic passed through to matching for the verified-
            claims path; omit for the unverified (claims-ready) seam.

        Returns
        -------
        LoopResult
            The final lifecycle state (``sold`` on a happy run), the acquisition
            and resale drafts, and the buyer-side match of the same property.

        Raises
        ------
        IllegalTransition
            If the lifecycle is driven out of order (guarded by PropertyState).
        ValueError
            If the seller acquisition does not produce an in-band offer (no
            property is actually acquired), or if the buyer flow does not match
            the listed property (nothing to resell) — the loop refuses to mark a
            property acquired/sold without the backing drafted offer.
        """
        address = seller_request.address

        # --- 1. SELLER FLOW: acquire the property. ------------------------- #
        # Reuse the seller-side Closer for the acquisition draft (band + UPL +
        # handoff + awaiting-broker emission are its single implementation).
        closer = Closer(
            offer_sink=self.offer_sink,
            handoff_sink=self.handoff_sink,
            buyer_name=buyer_name_acquisition,
        )
        acquisition: CloseResult = closer.draft_offer(
            seller_request,
            seller_valuation,
            acquisition_band,
            lead_id=lead_id,
            seller_name=seller_name,
            effective_date=effective_date,
            closing_date=closing_date,
            price=acquisition_price,
        )
        if acquisition.offer is None:
            # The acquisition escalated (out-of-band / UPL): no property is
            # actually acquired, so there is nothing to list/resell.
            raise ValueError(
                "acquisition did not produce an in-band offer "
                f"({acquisition.reason}); property not acquired"
            )

        # The drafted acquisition offer means the property is ACQUIRED. The
        # PropertyState enters at ACQUIRED by construction (system-of-record
        # projection: Rails would create the Property row here).
        property_state = PropertyState(property_id=property_id, address=address)

        # --- 2. LIST the acquired property (guarded transition). ----------- #
        property_state.list_()

        # --- 3. BUYER FLOW: re-discover the SAME property, draft resale. --- #
        # Present the now-listed property as a candidate to the buyer matcher,
        # carrying the SAME property_id (as listing_id) and address. This is the
        # seam: one property identity crosses from the seller side to the buyer
        # side. Neutral listing facts (from listing_extras) let the buyer's
        # criteria actually match.
        candidate = self._listed_candidate(property_state, listing_extras)
        matches = match_properties(buyer_request, [candidate], critic=critic)
        if not matches:
            raise ValueError(
                "buyer flow did not match the listed property "
                f"{address!r}; nothing to resell (check buyer criteria vs "
                "listing_extras)"
            )
        match = matches[0]

        # The matched property must be the same identity we acquired + listed.
        assert match.listing_id == property_id, (
            "loop invariant: the buyer flow must match the SAME property "
            f"({match.listing_id!r} != {property_id!r})"
        )

        # A buyer purchase offer puts the property UNDER OFFER.
        property_state.mark_under_offer()

        resale: BuyerCloseResult = draft_buyer_offer(
            buyer_request,
            match,
            resale_terms,
            resale_band,
            lead_id=lead_id,
            seller_name=resale_seller_name or seller_name,
            buyer_name=buyer_name_resale,
            effective_date=effective_date,
            closing_date=closing_date,
            price=resale_price,
            offer_sink=self.offer_sink,
            handoff_sink=self.handoff_sink,
            now=self.now,
        )
        if resale.offer is None:
            # The resale escalated: leave the property UNDER_OFFER (not sold) and
            # surface the escalation rather than faking a completion.
            raise ValueError(
                "resale did not produce an in-band offer "
                f"({resale.reason}); property under offer but not sold"
            )

        # --- 4. SELL: the resale offer drafted -> property is sold. -------- #
        property_state.sell()

        return LoopResult(
            property_state=property_state,
            acquisition=acquisition,
            resale=resale,
            match=match,
        )

    def _listed_candidate(
        self,
        property_state: PropertyState,
        listing_extras: Optional[Mapping[str, Any]],
    ) -> dict:
        """Build the buyer-matcher candidate for the listed property.

        Carries the run's identity (``listing_id``/``address``) plus any neutral
        listing facts the buyer's criteria filter on. Only the matcher's neutral
        allow-list is ever read off it, so extra fields are inert.
        """
        candidate: dict = dict(listing_extras or {})
        candidate["listing_id"] = property_state.property_id
        candidate["address"] = property_state.address
        return candidate


def run_loop(
    *,
    property_id: str,
    seller_request: SellerRequest,
    seller_valuation: Valuation,
    acquisition_band: AuthorizedBand,
    buyer_request: BuyerRequest,
    resale_band: AuthorizedBand,
    resale_terms: object,
    lead_id: str,
    seller_name: str,
    offer_sink: Optional[OfferSink] = None,
    handoff_sink: Optional[HandoffSink] = None,
    now: Optional[datetime] = None,
    **kwargs: Any,
) -> LoopResult:
    """Module-level convenience: construct a :class:`PropertyLoop` and run once.

    A thin wrapper so callers can drive the demo spine without first building a
    :class:`PropertyLoop`. All sinks/clock are injected (default in-memory fakes
    + ``utcnow``) so the run stays hermetic and deterministic. Extra keyword
    arguments are forwarded to :meth:`PropertyLoop.run_loop`.
    """
    loop = PropertyLoop(
        offer_sink=offer_sink if offer_sink is not None else FakeOfferSink(),
        handoff_sink=handoff_sink if handoff_sink is not None else FakeHandoffSink(),
        now=now,
    )
    return loop.run_loop(
        property_id=property_id,
        seller_request=seller_request,
        seller_valuation=seller_valuation,
        acquisition_band=acquisition_band,
        buyer_request=buyer_request,
        resale_band=resale_band,
        resale_terms=resale_terms,
        lead_id=lead_id,
        seller_name=seller_name,
        **kwargs,
    )


__all__ = [
    "PropertyStatus",
    "IllegalTransition",
    "PropertyState",
    "LoopResult",
    "PropertyLoop",
    "run_loop",
]
