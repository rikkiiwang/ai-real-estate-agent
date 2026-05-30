"""U7 Fair Housing output-rail tests (deterministic, stdlib only).

Covers AE2 / R12. The rail is the *wording* gate before send, separate from
factual verification:

* a NEUTRAL factual neighborhood answer (price, beds, commute) PASSES;
* "is this a safe/family-friendly neighborhood?" answered with an opinion is
  REDIRECTED to neutral third-party sources, not answered;
* output containing a protected-class proxy is BLOCKED and escalates;
* a school-quality / crime question is redirected to a third-party source per
  HUD steering guidance;
* every trip carries a logged ``reason`` and is loggable (``to_dict``);
* the equal-service guarantee is documented and performs no branching.
"""
from __future__ import annotations

from brain.lawyer.fair_housing import (
    DENY_LIST,
    EQUAL_SERVICE_GUARANTEE,
    FairHousingResult,
    equal_service,
    find_protected_terms,
    scan_output,
)
from brain.lawyer.redirect_policy import (
    build_redirect,
    detect_subjective_topics,
    is_neutral_factual,
    review_output,
)


# --------------------------------------------------------------------------- #
# AE2 happy path: neutral factual answer passes.
# --------------------------------------------------------------------------- #
def test_neutral_factual_answer_passes():
    draft = (
        "The home is listed at $525,000, has 3 beds and 2 baths, 1,840 sqft, "
        "a property tax rate of 2.1%, and a 12-mile commute to downtown."
    )
    result = review_output(draft, question="What's the price, beds, and commute?")
    assert isinstance(result, FairHousingResult)
    assert result.allowed is True
    assert result.escalate is False
    assert result.redirected_response is None
    assert result.reason  # always logged


def test_is_neutral_factual_recognizes_objective_topics():
    assert is_neutral_factual("What is the asking price and how many bedrooms?")
    assert not is_neutral_factual("Is it a safe neighborhood?")
    # Mixed: a neutral topic plus a subjective one is still subjective.
    assert not is_neutral_factual("What's the price, and is it a good neighborhood?")


# --------------------------------------------------------------------------- #
# AE2 critical: subjective question answered with an opinion -> REDIRECTED.
# --------------------------------------------------------------------------- #
def test_subjective_safety_question_is_redirected_not_answered():
    # The generator drafted an opinion answer to a subjective question.
    draft = "Yes, this is a very safe area and great for families."
    result = review_output(draft, question="Is this a safe, family-friendly neighborhood?")
    assert result.allowed is False
    assert result.escalate is True
    assert result.redirected_response is not None
    # Redirect points at neutral third-party sources, never an opinion.
    assert "hud" in result.redirected_response.lower()
    assert result.reason


def test_pure_redirect_draft_is_allowed():
    # A draft that already redirects (no opinion asserted) passes.
    redirect = build_redirect(["safety"])
    result = review_output(redirect, question="Is it safe around here?")
    assert result.allowed is True
    assert result.escalate is False


# --------------------------------------------------------------------------- #
# AE2 critical: protected-class proxy in output -> BLOCKED + escalates.
# --------------------------------------------------------------------------- #
def test_proxy_in_output_is_blocked_and_escalates():
    draft = "This is a family-friendly home in a safe neighborhood."
    result = scan_output(draft)
    assert result.allowed is False
    assert result.escalate is True
    assert result.matches  # offending phrases captured for audit
    sources = {m.source for m in result.matches}
    assert "proxy" in sources


def test_protected_class_term_is_blocked():
    draft = "This block is mostly Hispanic families with young children."
    result = scan_output(draft)
    assert result.allowed is False
    assert result.escalate is True
    cats = {m.category for m in result.matches}
    # Hits a federal class (national origin / familial status).
    assert cats & {"national_origin", "familial_status", "race", "age"}


def test_austin_ordinance_term_is_blocked():
    draft = "We don't accept Section 8 vouchers at this listing."
    result = scan_output(draft)
    assert result.allowed is False
    assert result.escalate is True
    assert any(m.source == "austin" for m in result.matches)


def test_demographic_descriptor_proxy_blocked():
    draft = "Is this a good neighborhood for people like you? Absolutely."
    result = scan_output(draft)
    assert result.allowed is False
    assert any(m.category == "demographic_descriptor" for m in result.matches)


# --------------------------------------------------------------------------- #
# AE2 edge: school-quality / crime question redirected to third-party source.
# --------------------------------------------------------------------------- #
def test_school_quality_question_redirected_to_third_party():
    draft = "Yes, the schools here are excellent and highly rated."
    result = review_output(draft, question="Are the schools good in this area?")
    assert result.allowed is False
    assert result.escalate is True
    assert result.redirected_response is not None
    # Points at the Texas Education Agency school ratings portal.
    assert "txschools" in result.redirected_response.lower() or \
        "texas education agency" in result.redirected_response.lower()


def test_crime_question_redirected_to_public_data():
    draft = "No, the crime rate here is very low, don't worry."
    result = review_output(draft, question="What's the crime rate like here?")
    assert result.allowed is False
    assert result.escalate is True
    assert result.redirected_response is not None
    assert "crime" in result.redirected_response.lower()


def test_detect_subjective_topics_data_driven():
    assert "schools" in detect_subjective_topics("how are the schools?")
    assert "crime" in detect_subjective_topics("is there crime here")
    assert "safety" in detect_subjective_topics("is it safe to live here")
    assert detect_subjective_topics("What is the lot size?") == []


# --------------------------------------------------------------------------- #
# Every trip carries a logged reason and is loggable.
# --------------------------------------------------------------------------- #
def test_trip_carries_logged_reason_and_is_loggable():
    result = scan_output("a great area, family-friendly, no kids welcome")
    assert result.escalate is True
    assert "BLOCKED" in result.reason
    d = result.to_dict()
    assert isinstance(d, dict)
    assert d["allowed"] is False
    assert d["escalate"] is True
    assert d["reason"] == result.reason
    assert isinstance(d["matches"], list) and d["matches"]


def test_find_protected_terms_is_word_boundary():
    # "therapist" must not match "rape"-style substrings; "class" not "race".
    clean = find_protected_terms("The classic floor plan has a large pantry.")
    assert clean == []
    hit = find_protected_terms("a safe neighborhood")
    assert hit and hit[0].source == "proxy"


# --------------------------------------------------------------------------- #
# Deny-list is data and easy to extend; equal-service is a documented marker.
# --------------------------------------------------------------------------- #
def test_deny_list_is_data_and_nonempty():
    assert len(DENY_LIST) > 50
    sources = {t.source for t in DENY_LIST}
    assert sources == {"federal", "austin", "proxy"}


def test_equal_service_is_documented_marker_no_branching():
    text = equal_service()
    assert text == EQUAL_SERVICE_GUARANTEE
    # It documents the no-branching guarantee.
    assert "must not branch" in text.lower()
    # It is constant — takes no per-user input, so it cannot branch on attrs.
    assert equal_service() == equal_service()
