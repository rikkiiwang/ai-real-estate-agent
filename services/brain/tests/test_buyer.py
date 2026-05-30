"""U14 tests — buyer qualification (intake) + property matching (Python).

Covers R5/R6 (qualification + the orchestrator seam) and R3/R11/R12 on the buyer
side: a *qualified* buyer request becomes a structured
:class:`~brain.orchestrator.buyer_intake.BuyerRequest`, and
:func:`~brain.orchestrator.matching.match_properties` matches it against injected
candidate listings on NEUTRAL criteria only, surfacing cited intelligence.

Scenarios:

INTAKE
* STRUCTURE — a pre-approved buyer with a timeline qualifies high-intent and
  becomes an orchestrator-ready request with neutral criteria + a neutral query.
* DERIVED INTENT — financing-ready + timeline derives high-intent; missing
  either stays low-intent (conservative default).
* STATE SEAM — the request projects onto the U10 orchestrator state keys.
* EQUAL SERVICE — the SAME output regardless of an inferred-attribute field.
* NEUTRAL ALLOW-LIST — only allow-listed neutral facts survive.
* REQUIRED FIELD — no search criteria raises.

MATCHING
* HAPPY PATH — a pre-approved buyer's criteria yield matches whose valuation +
  photo intelligence is surfaced as CITED, verified claims (through the Critic +
  Fair-Housing path).
* EQUAL SERVICE — identical match set whether or not an inferred-attribute field
  is present on the request OR the candidates (no protected-class proxy).
* NO FABRICATION — over-constrained criteria return an EMPTY match list.
* READY-FOR-VERIFICATION SEAM — with no critic injected, claims come back bound
  to their source ids (citable) but unverified.
"""
from __future__ import annotations

import pytest

from brain.lawyer.critic import Critic
from brain.lawyer.entailment import FakeEntailer
from brain.orchestrator.buyer_intake import (
    INTENT_HIGH,
    INTENT_LOW,
    BuyerRequest,
    buyer_intake,
)
from brain.orchestrator.matching import (
    MatchClaim,
    PropertyMatch,
    match_properties,
)
from brain.rag import FakeEmbedder, InMemoryVectorStore, Retriever
from brain.valuation import Fact as ValFact, Valuation
from brain.vision import Finding


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
CRITERIA = {"min_beds": 3, "min_baths": 2, "max_price": 600_000, "location": "Austin"}


def _valuation() -> Valuation:
    """A sufficient-data valuation with one source-cited feature fact."""
    return Valuation(
        sufficient_data=True,
        estimate=525_000.0,
        low=495_000.0,
        high=555_000.0,
        facts=[
            ValFact(
                source_id="tcad:123",
                kind="feature:sqft",
                description="Living area (sqft)",
                contribution=42_000.0,
            )
        ],
    )


def _granite_finding() -> Finding:
    return Finding(
        kind="feature",
        label="granite_countertops",
        confidence=0.92,
        evidence_photo_id="photo-1",
    )


def _candidate(**overrides):
    """A neutral candidate listing dict that satisfies CRITERIA by default."""
    base = {
        "listing_id": "L-1",
        "address": "10 Oak St Austin TX",
        "beds": 4,
        "baths": 3,
        "price": 540_000,
        "sqft": 2100,
        "location": "Austin",
        "property_type": "single_family",
        "valuation": _valuation(),
        "photo_findings": [_granite_finding()],
    }
    base.update(overrides)
    return base


def _critic() -> Critic:
    """A real Critic over the in-memory RAG store + deterministic entailer."""
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedder)
    retriever = Retriever(store=store, embedder=embedder)
    return Critic(retriever=retriever, entailer=FakeEntailer())


# --------------------------------------------------------------------------- #
# Intake
# --------------------------------------------------------------------------- #
def test_preapproved_buyer_with_timeline_qualifies_high_intent():
    req = buyer_intake(
        "",  # let qualification derive from neutral fields
        neutral_fields={**CRITERIA, "pre_approved": True, "timeline": "30 days"},
    )
    assert isinstance(req, BuyerRequest)
    assert req.high_intent is True
    assert req.intent == INTENT_HIGH
    assert req.criteria == CRITERIA
    assert req.qualification == {"pre_approved": True, "timeline": "30 days"}
    # The query is the neutral search-oriented prompt the orchestrator runs.
    assert "min_beds=3" in req.query
    assert "location=Austin" in req.query


def test_intent_derived_conservatively_from_neutral_qualification():
    # Financing-ready but no timeline -> low intent.
    no_timeline = buyer_intake("", neutral_fields={**CRITERIA, "pre_approved": True})
    assert no_timeline.high_intent is False
    assert no_timeline.intent == INTENT_LOW

    # Timeline but no financing readiness -> low intent.
    no_financing = buyer_intake("", neutral_fields={**CRITERIA, "timeline": "asap"})
    assert no_financing.high_intent is False

    # Proof of funds counts as financing readiness.
    cash = buyer_intake(
        "", neutral_fields={**CRITERIA, "proof_of_funds": True, "timeline": "asap"}
    )
    assert cash.high_intent is True

    # An explicit Voice-side high-intent label is honored.
    labeled = buyer_intake(INTENT_HIGH, neutral_fields=CRITERIA)
    assert labeled.high_intent is True


def test_projects_onto_orchestrator_state_keys():
    req = buyer_intake(INTENT_HIGH, neutral_fields=CRITERIA)
    state = req.to_orchestrator_state()
    assert state["query"] == req.query
    assert set(state) == {"query"}


def test_intake_equal_service_inferred_attribute_does_not_change_output():
    baseline = buyer_intake(
        "", neutral_fields={**CRITERIA, "pre_approved": True, "timeline": "30 days"}
    )
    with_inferred = buyer_intake(
        "",
        neutral_fields={
            **CRITERIA,
            "pre_approved": True,
            "timeline": "30 days",
            # assorted inferred / proxy attributes mixed in
            "race": "white",
            "family_status": "has children",
            "age": "senior",
            "good_schools": True,
        },
    )
    assert with_inferred == baseline
    assert with_inferred.criteria == baseline.criteria
    assert with_inferred.query == baseline.query


def test_intake_only_neutral_allowlist_survives():
    req = buyer_intake(
        INTENT_HIGH,
        neutral_fields={
            "min_beds": 2,
            "max_price": 400_000,
            "ethnicity": "latino",  # not neutral -> dropped
            "location": "   ",       # blank value -> dropped
        },
    )
    assert req.criteria == {"min_beds": 2, "max_price": 400_000}


def test_intake_requires_search_criteria():
    with pytest.raises(ValueError):
        buyer_intake(INTENT_HIGH, neutral_fields={"pre_approved": True})


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
def test_preapproved_buyer_gets_matches_with_cited_verified_intelligence():
    req = buyer_intake(
        "", neutral_fields={**CRITERIA, "pre_approved": True, "timeline": "30 days"}
    )
    matches = match_properties(req, [_candidate()], critic=_critic())

    assert len(matches) == 1
    match = matches[0]
    assert isinstance(match, PropertyMatch)
    assert match.listing_id == "L-1"
    # Cited intelligence is surfaced: every claim carries a backing source id.
    assert match.claims
    assert all(isinstance(c, MatchClaim) for c in match.claims)
    assert all(c.source_id for c in match.claims)
    # Through the Critic + FH path, claims are verified (entailed + cited) and
    # the wording rail allowed the surfaced text.
    assert match.fair_housing is not None and match.fair_housing.allowed
    assert match.verified_claims
    assert all(c.verified for c in match.verified_claims)
    # The valuation + photo finding both surfaced.
    kinds = {c.kind for c in match.verified_claims}
    assert "valuation_run" in kinds
    assert "photo_finding" in kinds


def test_matching_never_uses_protected_class_proxies_equal_service():
    """Same matches whether or not an inferred-attribute field is present."""
    base_req = buyer_intake(INTENT_HIGH, neutral_fields=CRITERIA)
    candidates = [_candidate(listing_id="A"), _candidate(listing_id="B", beds=2)]

    baseline = match_properties(base_req, candidates)

    # Inferred attributes smuggled onto BOTH the request criteria source and the
    # candidates must not change the match set.
    tainted_candidates = [
        _candidate(listing_id="A", race="white", family_status="children"),
        _candidate(listing_id="B", beds=2, religion="christian"),
    ]
    # buyer_intake already drops non-neutral fields, but pass them anyway.
    tainted_req = buyer_intake(
        INTENT_HIGH,
        neutral_fields={**CRITERIA, "race": "white", "good_schools": True},
    )
    tainted = match_properties(tainted_req, tainted_candidates)

    baseline_ids = [m.listing_id for m in baseline]
    tainted_ids = [m.listing_id for m in tainted]
    assert baseline_ids == tainted_ids == ["A"]  # B fails min_beds either way
    # And the neutral fields actually compared are identical.
    assert [m.criteria_met for m in baseline] == [m.criteria_met for m in tainted]


def test_over_constrained_criteria_returns_no_matches_no_fabrication():
    # A price ceiling below every candidate -> empty, never invented.
    req = buyer_intake(
        INTENT_HIGH,
        neutral_fields={"min_beds": 3, "max_price": 100_000, "location": "Austin"},
    )
    matches = match_properties(req, [_candidate(), _candidate(listing_id="L-2")])
    assert matches == []

    # An impossible bed count -> empty.
    req2 = buyer_intake(INTENT_HIGH, neutral_fields={"min_beds": 10})
    assert match_properties(req2, [_candidate()], critic=_critic()) == []


def test_claims_ready_for_verification_when_no_critic_injected():
    """No critic -> claims returned unverified but bound to source ids (seam)."""
    req = buyer_intake(INTENT_HIGH, neutral_fields=CRITERIA)
    matches = match_properties(req, [_candidate()])
    assert len(matches) == 1
    match = matches[0]
    assert match.fair_housing is None
    assert match.claims  # intelligence surfaced
    assert all(not c.verified for c in match.claims)
    assert all(c.source_id and c.kind for c in match.claims)  # citable
    assert match.verified_claims == []


def test_candidate_without_intelligence_matches_with_no_claims_not_fabricated():
    """A bare candidate (no valuation/photos) matches but surfaces no claims."""
    req = buyer_intake(INTENT_HIGH, neutral_fields={"min_beds": 3})
    bare = {"listing_id": "bare", "address": "1 Bare St", "beds": 3}
    matches = match_properties(req, [bare], critic=_critic())
    assert len(matches) == 1
    assert matches[0].claims == []  # nothing grounded -> nothing surfaced
