"""Seller intake — the orchestrator seam for U11.

The Voice transport (``services/voice``) holds the conversation thread and
triages intent; this module is the orchestrator-side counterpart. It takes a
*qualified* seller request — an address, a triaged intent label, and the
neutral, transaction-relevant fields the Voice channel collected — and turns it
into a structured :class:`SellerRequest` the orchestrator can act on. That
structured request is the thing that feeds the downstream valuation -> Critic
loop (U10): its ``address`` scopes RAG retrieval and its ``query`` kicks off the
grounded generate pass.

Equal-service guarantee (Fair Housing, U7)
------------------------------------------
This function MUST NOT branch on inferred protected attributes. Qualification
already happens on the Voice side using only neutral signals; here we merely
*structure* the request. Any field that is not a neutral, transaction-relevant
fact (an inferred race/age/family-status/etc. signal, or a proxy for one) is
ignored — it never changes the produced request. The unit test pins this: the
same address + intent + neutral fields produce byte-identical output regardless
of any inferred-attribute field passed alongside. See
:data:`brain.lawyer.fair_housing.EQUAL_SERVICE_GUARANTEE`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

# Neutral, transaction-relevant fields the intake will carry through. Anything
# NOT on this allow-list is dropped — this is what makes "ignore inferred
# attributes" a structural guarantee rather than a per-field branch. Extend this
# tuple to admit more *neutral* facts; never add a protected-class proxy.
NEUTRAL_FIELDS: tuple[str, ...] = (
    "timeline",       # stated time-frame to sell (e.g. "30 days", "asap")
    "motivation",     # stated reason to sell (relocation, downsizing, ...)
    "property_type",  # single-family, condo, ...
    "beds",
    "baths",
    "condition",      # seller-stated condition
    "occupancy",      # owner-occupied / tenant / vacant
    "asking_price",   # seller's stated number, if any
)

# Intent labels produced by the Voice-side triage (U11 ``qualify.go``). Kept in
# sync as plain strings (no enum dependency across the language boundary).
INTENT_HIGH = "high_intent_seller"
INTENT_LOW = "low_intent_browser"


@dataclass(frozen=True)
class SellerRequest:
    """A structured, orchestrator-ready seller request.

    Produced by :func:`seller_intake` from a qualified intake. It carries only
    neutral, transaction-relevant data:

    * ``address`` — the property the run is about; scopes RAG retrieval and is
      copied straight onto the orchestrator state's ``address`` key.
    * ``intent`` — the Voice-side triage label (``INTENT_HIGH`` / ``INTENT_LOW``).
    * ``high_intent`` — convenience boolean derived from ``intent``.
    * ``neutral_fields`` — the allow-listed neutral facts collected this far
      (timeline, motivation, ...); never any inferred attribute.
    * ``query`` — the customer-facing request string the orchestrator's generate
      pass consumes (a neutral, valuation-oriented prompt).

    ``frozen`` so a structured request can't be mutated after triage.
    """

    address: str
    intent: str
    high_intent: bool
    query: str
    neutral_fields: Mapping[str, Any] = field(default_factory=dict)

    def to_orchestrator_state(self) -> dict[str, Any]:
        """Project into the kwargs the U10 orchestrator state expects.

        Only ``address`` and ``query`` are state keys today; the neutral fields
        ride along for downstream valuation features without ever becoming a
        branch in the agent loop.
        """
        return {"address": self.address, "query": self.query}


def _select_neutral_fields(fields: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep only allow-listed neutral fields with a non-empty value.

    This is the equal-service mechanism: by selecting from a fixed neutral
    allow-list (rather than copying the caller's dict wholesale) any inferred
    protected attribute or proxy passed alongside is structurally dropped — it
    cannot reach the produced request, so it cannot change behavior downstream.
    """
    if not fields:
        return {}
    selected: dict[str, Any] = {}
    for key in NEUTRAL_FIELDS:
        value = fields.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        selected[key] = value
    return selected


def _build_query(address: str, neutral_fields: Mapping[str, Any]) -> str:
    """Compose the neutral valuation-oriented query the orchestrator runs.

    Deterministic and wording-neutral so the Critic/Fair-Housing rails have a
    grounded request to verify against — never references any attribute outside
    the neutral allow-list.
    """
    query = f"Provide a cited cash-offer valuation for {address}."
    timeline = neutral_fields.get("timeline")
    if timeline:
        query += f" Seller timeline to sell: {timeline}."
    return query


def seller_intake(
    address: str,
    intent: str,
    neutral_fields: Optional[Mapping[str, Any]] = None,
) -> SellerRequest:
    """Turn a qualified seller intake into a structured orchestrator request.

    Parameters
    ----------
    address:
        The subject property address (collected + qualified on the Voice side).
        Required and non-empty — without an address there is nothing to value.
    intent:
        The Voice-side triage label (``INTENT_HIGH`` or ``INTENT_LOW``). Any
        other value is treated as low-intent (conservative default); the label
        is carried, not recomputed, here.
    neutral_fields:
        Neutral, transaction-relevant facts the channel collected. Only the
        :data:`NEUTRAL_FIELDS` allow-list survives into the request; any
        inferred-attribute field is ignored (equal-service guarantee).

    Returns
    -------
    SellerRequest
        The structured request that feeds valuation -> Critic.

    Raises
    ------
    ValueError
        If ``address`` is missing or blank.

    Notes
    -----
    Equal service: this function does not branch on inferred protected
    attributes. It selects neutral facts from a fixed allow-list, so an inferred
    attribute passed in ``neutral_fields`` produces the exact same output as if
    it were absent.
    """
    if not address or not address.strip():
        raise ValueError("seller_intake requires a non-empty address")

    address = address.strip()
    selected = _select_neutral_fields(neutral_fields)
    high_intent = intent == INTENT_HIGH
    normalized_intent = INTENT_HIGH if high_intent else INTENT_LOW
    query = _build_query(address, selected)

    return SellerRequest(
        address=address,
        intent=normalized_intent,
        high_intent=high_intent,
        query=query,
        neutral_fields=selected,
    )


__all__ = [
    "SellerRequest",
    "seller_intake",
    "NEUTRAL_FIELDS",
    "INTENT_HIGH",
    "INTENT_LOW",
]
