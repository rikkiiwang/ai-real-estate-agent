"""U11 tests — the orchestrator-side seller intake seam (Python).

Covers R5/R6 on the orchestrator side: a *qualified* seller request (address +
triaged intent + neutral fields) is turned into a structured
:class:`SellerRequest` the orchestrator can act on (the thing that feeds
valuation -> Critic).

Scenarios:

* STRUCTURE — a qualified high-intent request becomes an orchestrator-ready
  request carrying the address, intent, and a neutral valuation query.
* STATE SEAM — the request projects onto the U10 orchestrator state keys.
* EQUAL SERVICE — the SAME output is produced regardless of an inferred-
  attribute field passed alongside the neutral ones (no branching).
* NEUTRAL ALLOW-LIST — only allow-listed neutral facts survive.
"""
from __future__ import annotations

import pytest

from brain.orchestrator.seller_intake import (
    INTENT_HIGH,
    INTENT_LOW,
    SellerRequest,
    seller_intake,
)

ADDRESS = "123 Main St Austin TX"


def test_qualified_high_intent_becomes_structured_request():
    req = seller_intake(
        ADDRESS,
        INTENT_HIGH,
        neutral_fields={"timeline": "30 days", "motivation": "relocation"},
    )
    assert isinstance(req, SellerRequest)
    assert req.address == ADDRESS
    assert req.intent == INTENT_HIGH
    assert req.high_intent is True
    assert req.neutral_fields == {"timeline": "30 days", "motivation": "relocation"}
    # The query is the valuation-oriented prompt the orchestrator runs.
    assert ADDRESS in req.query
    assert "30 days" in req.query


def test_low_intent_label_carried_and_default_is_conservative():
    low = seller_intake(ADDRESS, INTENT_LOW)
    assert low.intent == INTENT_LOW
    assert low.high_intent is False
    # An unknown label is treated as low-intent (conservative default).
    unknown = seller_intake(ADDRESS, "something_else")
    assert unknown.intent == INTENT_LOW
    assert unknown.high_intent is False


def test_projects_onto_orchestrator_state_keys():
    req = seller_intake(ADDRESS, INTENT_HIGH, neutral_fields={"timeline": "asap"})
    state = req.to_orchestrator_state()
    assert state["address"] == ADDRESS
    assert state["query"] == req.query
    # Only the seam keys are projected.
    assert set(state) == {"address", "query"}


def test_equal_service_inferred_attribute_does_not_change_output():
    """Equal service: an inferred-attribute field must not change the output."""
    neutral = {"timeline": "30 days", "motivation": "downsizing"}
    baseline = seller_intake(ADDRESS, INTENT_HIGH, neutral_fields=neutral)

    # Same call, but with assorted inferred / proxy attributes mixed in.
    with_inferred = seller_intake(
        ADDRESS,
        INTENT_HIGH,
        neutral_fields={
            **neutral,
            "race": "white",
            "family_status": "has children",
            "age": "senior",
            "religion": "christian",
            "good_schools": True,
        },
    )

    assert with_inferred == baseline
    assert with_inferred.neutral_fields == baseline.neutral_fields
    assert with_inferred.query == baseline.query


def test_only_neutral_allowlist_survives():
    req = seller_intake(
        ADDRESS,
        INTENT_HIGH,
        neutral_fields={
            "timeline": "60 days",
            "beds": 3,
            "occupancy": "owner",
            "ethnicity": "latino",  # not neutral -> dropped
            "": "blank-key",
            "motivation": "   ",      # blank value -> dropped
        },
    )
    assert req.neutral_fields == {"timeline": "60 days", "beds": 3, "occupancy": "owner"}


def test_missing_address_raises():
    with pytest.raises(ValueError):
        seller_intake("   ", INTENT_HIGH)
