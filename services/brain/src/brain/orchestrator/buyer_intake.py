"""Buyer intake — the orchestrator seam for U14 (buyer side of U11).

The Voice transport (``services/voice``) holds the conversation thread and
triages intent; this module is the orchestrator-side counterpart, mirroring
:mod:`brain.orchestrator.seller_intake`. It takes a *qualified* buyer request —
a triaged intent label and the neutral, transaction-relevant fields the Voice
channel collected (search criteria + qualification signals like pre-approval and
timeline) — and turns it into a structured :class:`BuyerRequest` the orchestrator
can act on. That structured request feeds the downstream property-matching pass
(:mod:`brain.orchestrator.matching`): its ``criteria`` scope the candidate match
and its ``query`` kicks off the grounded generate/verify loop (U10) for the
cited intelligence surfaced on each match.

Qualification (R5)
------------------
Buyer qualification is a NEUTRAL, transaction-relevant judgement only: a buyer
is "high intent" when the channel collected a financing readiness signal
(pre-approval / proof of funds) *and* a concrete purchase timeline. That logic
reads only allow-listed neutral fields — never an inferred protected attribute.
The Voice side may already have triaged; here we carry that label, and (when it
was left unset / non-committal) derive it conservatively from the neutral
qualification fields. The default is low-intent.

Equal-service guarantee (Fair Housing, U7)
------------------------------------------
This function MUST NOT branch on inferred protected attributes. Any field that
is not a neutral, transaction-relevant fact (an inferred race/age/family-status/
etc. signal, or a proxy for one) is ignored — it never changes the produced
request. The unit test pins this: the same intent + neutral fields produce
byte-identical output regardless of any inferred-attribute field passed
alongside. See :data:`brain.lawyer.fair_housing.EQUAL_SERVICE_GUARANTEE`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

# Neutral, transaction-relevant fields the buyer intake carries through. Anything
# NOT on this allow-list is dropped — this is what makes "ignore inferred
# attributes" a structural guarantee rather than a per-field branch. Extend this
# tuple to admit more *neutral* facts; never add a protected-class proxy.
#
# Split into two roles, both neutral:
#   * SEARCH CRITERIA — what the buyer is shopping for (drives matching).
#   * QUALIFICATION   — financing readiness + timeline (drives intent triage).
NEUTRAL_CRITERIA_FIELDS: tuple[str, ...] = (
    "min_beds",        # minimum bedroom count
    "min_baths",       # minimum bathroom count
    "max_price",       # price ceiling (budget)
    "min_sqft",        # minimum living area (sqft)
    "location",        # desired location / area string (a place, NOT a proxy)
    "property_type",   # single-family, condo, ...
)
NEUTRAL_QUALIFICATION_FIELDS: tuple[str, ...] = (
    "pre_approved",    # financing readiness: mortgage pre-approval
    "proof_of_funds",  # financing readiness: cash proof of funds
    "timeline",        # stated time-frame to buy (e.g. "30 days", "asap")
)

# The full neutral allow-list (criteria + qualification).
NEUTRAL_FIELDS: tuple[str, ...] = NEUTRAL_CRITERIA_FIELDS + NEUTRAL_QUALIFICATION_FIELDS

# Intent labels produced by the Voice-side triage (U11/U14 ``qualify.go``). Kept
# in sync as plain strings (no enum dependency across the language boundary).
INTENT_HIGH = "high_intent_buyer"
INTENT_LOW = "low_intent_browser"


@dataclass(frozen=True)
class BuyerRequest:
    """A structured, orchestrator-ready buyer request.

    Produced by :func:`buyer_intake` from a qualified intake. It carries only
    neutral, transaction-relevant data:

    * ``intent`` — the triage label (``INTENT_HIGH`` / ``INTENT_LOW``).
    * ``high_intent`` — convenience boolean derived from ``intent``.
    * ``criteria`` — the allow-listed neutral SEARCH criteria (beds/baths/price/
      sqft/location/...); the thing :func:`~brain.orchestrator.matching.match_properties`
      filters candidates on. Never any inferred attribute or proxy.
    * ``qualification`` — the allow-listed neutral QUALIFICATION facts
      (pre-approval, proof of funds, timeline) the intent triage rested on.
    * ``query`` — the customer-facing request string the orchestrator's generate
      pass consumes (a neutral, search-oriented prompt).

    ``frozen`` so a structured request can't be mutated after triage.
    """

    intent: str
    high_intent: bool
    query: str
    criteria: Mapping[str, Any] = field(default_factory=dict)
    qualification: Mapping[str, Any] = field(default_factory=dict)

    def to_orchestrator_state(self) -> dict[str, Any]:
        """Project into the kwargs the U10 orchestrator state expects.

        Only ``query`` is a state key for the buyer flow today (there is no
        single subject ``address`` — matching produces candidates). The neutral
        criteria ride along on the request for the matching pass without ever
        becoming a branch in the agent loop.
        """
        return {"query": self.query}


def _select(
    fields: Optional[Mapping[str, Any]],
    allow_list: tuple[str, ...],
) -> dict[str, Any]:
    """Keep only allow-listed neutral fields with a non-empty value.

    This is the equal-service mechanism: by selecting from a fixed neutral
    allow-list (rather than copying the caller's dict wholesale) any inferred
    protected attribute or proxy passed alongside is structurally dropped — it
    cannot reach the produced request, so it cannot change behavior downstream.

    A ``False`` boolean (e.g. ``pre_approved=False``) is a meaningful neutral
    fact and is kept; only ``None`` and blank strings are treated as "not given".
    """
    if not fields:
        return {}
    selected: dict[str, Any] = {}
    for key in allow_list:
        value = fields.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        selected[key] = value
    return selected


def _is_financing_ready(qualification: Mapping[str, Any]) -> bool:
    """True iff a neutral financing-readiness signal is present and affirmative."""
    return bool(qualification.get("pre_approved")) or bool(
        qualification.get("proof_of_funds")
    )


def _derive_high_intent(intent: str, qualification: Mapping[str, Any]) -> bool:
    """Decide high-intent from the carried label and neutral qualification facts.

    A buyer is high-intent when financing-ready (pre-approved / proof of funds)
    AND carrying a concrete timeline. If the Voice side already labeled the
    request ``INTENT_HIGH`` we honor it; an explicit ``INTENT_LOW`` is also
    honored. Any other / unset label falls back to the neutral derivation, with
    low-intent as the conservative default.

    This reads ONLY neutral fields — never an inferred protected attribute.
    """
    if intent == INTENT_HIGH:
        return True
    if intent == INTENT_LOW:
        return False
    return _is_financing_ready(qualification) and bool(qualification.get("timeline"))


def _build_query(criteria: Mapping[str, Any]) -> str:
    """Compose the neutral search-oriented query the orchestrator runs.

    Deterministic and wording-neutral so the Critic/Fair-Housing rails have a
    grounded request to verify against — never references any attribute outside
    the neutral allow-list. Criteria are rendered in a fixed order for stability.
    """
    query = "Surface cited matching listings for a buyer"
    parts: list[str] = []
    for key in NEUTRAL_CRITERIA_FIELDS:
        value = criteria.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        parts.append(f"{key}={value}")
    if parts:
        query += " with criteria " + ", ".join(parts)
    return query + "."


def buyer_intake(
    intent: str,
    neutral_fields: Optional[Mapping[str, Any]] = None,
) -> BuyerRequest:
    """Turn a qualified buyer intake into a structured orchestrator request.

    Parameters
    ----------
    intent:
        The Voice-side triage label (``INTENT_HIGH`` or ``INTENT_LOW``), or an
        unset/non-committal value to let qualification derive from the neutral
        fields. The label is carried, not re-invented, except for the
        conservative derivation documented in :func:`_derive_high_intent`.
    neutral_fields:
        Neutral, transaction-relevant facts the channel collected — both SEARCH
        criteria (beds/baths/price/sqft/location/...) and QUALIFICATION signals
        (pre-approval, proof of funds, timeline). Only the :data:`NEUTRAL_FIELDS`
        allow-list survives into the request; any inferred-attribute field is
        ignored (equal-service guarantee).

    Returns
    -------
    BuyerRequest
        The structured request that feeds property matching -> Critic.

    Raises
    ------
    ValueError
        If no neutral SEARCH criteria are supplied — there is nothing to match a
        buyer against without at least one criterion (mirrors seller_intake's
        "no address -> nothing to value" required-field guard).

    Notes
    -----
    Equal service: this function does not branch on inferred protected
    attributes. It selects neutral facts from a fixed allow-list, so an inferred
    attribute passed in ``neutral_fields`` produces the exact same output as if
    it were absent.
    """
    criteria = _select(neutral_fields, NEUTRAL_CRITERIA_FIELDS)
    if not criteria:
        raise ValueError(
            "buyer_intake requires at least one neutral search criterion "
            "(e.g. min_beds, max_price, location)"
        )

    qualification = _select(neutral_fields, NEUTRAL_QUALIFICATION_FIELDS)
    high_intent = _derive_high_intent(intent, qualification)
    normalized_intent = INTENT_HIGH if high_intent else INTENT_LOW
    query = _build_query(criteria)

    return BuyerRequest(
        intent=normalized_intent,
        high_intent=high_intent,
        query=query,
        criteria=criteria,
        qualification=qualification,
    )


__all__ = [
    "BuyerRequest",
    "buyer_intake",
    "NEUTRAL_FIELDS",
    "NEUTRAL_CRITERIA_FIELDS",
    "NEUTRAL_QUALIFICATION_FIELDS",
    "INTENT_HIGH",
    "INTENT_LOW",
]
