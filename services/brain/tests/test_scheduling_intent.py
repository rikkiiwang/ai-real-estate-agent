"""Scheduling-intent classifier tests (deterministic, stdlib only).

Covers spec §6 / plan Task A1. The classifier is the brain's small, honest,
LLM-free capability that recognizes "I want to tour / see / visit / book a
showing / set up an inspection" from neutral phrasing so the orchestrator can
route to the (Rails-owned) collision-aware slots UI.

Fair-Housing discipline (mirrors ``buyer_intake`` neutral-field rule): the
function reads ONLY tour/scheduling intent. It must never key off protected
attributes, and ``matched`` must never contain a protected-class term — even
when the message also mentions one.
"""
from __future__ import annotations

from brain.scheduling import SchedulingIntent, classify_scheduling_intent

# Protected-class surface terms, drawn from the Fair Housing deny-list, used to
# assert the scheduling classifier never matches on them.
from brain.lawyer.fair_housing import find_protected_terms


# --------------------------------------------------------------------------- #
# Result shape: a frozen dataclass with the contracted fields.
# --------------------------------------------------------------------------- #
def test_result_is_frozen_dataclass_with_contracted_fields():
    result = classify_scheduling_intent("Can I tour this house Friday?")
    assert isinstance(result, SchedulingIntent)
    assert isinstance(result.wants_scheduling, bool)
    assert result.kind in ("tour", "inspection", None)
    assert isinstance(result.matched, tuple)
    # Frozen: fields cannot be reassigned.
    import dataclasses

    assert dataclasses.is_dataclass(result)
    try:
        result.wants_scheduling = False  # type: ignore[misc]
        raised = False
    except dataclasses.FrozenInstanceError:
        raised = True
    assert raised


# --------------------------------------------------------------------------- #
# Positives: tour signals -> wants_scheduling True, kind == "tour".
# --------------------------------------------------------------------------- #
def test_tour_phrase_is_detected():
    result = classify_scheduling_intent("Can I tour this house Friday?")
    assert result.wants_scheduling is True
    assert result.kind == "tour"
    assert "tour" in result.matched


def test_schedule_a_showing_is_detected_as_tour():
    result = classify_scheduling_intent("I'd like to schedule a showing")
    assert result.wants_scheduling is True
    assert result.kind == "tour"
    assert result.matched  # non-empty


def test_see_the_house_is_detected_as_tour():
    for text in (
        "I want to see the house",
        "Could I see the home this weekend?",
        "can we see the place?",
    ):
        result = classify_scheduling_intent(text)
        assert result.wants_scheduling is True, text
        assert result.kind == "tour", text


def test_visit_is_detected_as_tour():
    result = classify_scheduling_intent("When can I visit?")
    assert result.wants_scheduling is True
    assert result.kind == "tour"
    assert "visit" in result.matched


def test_walk_through_variants_detected_as_tour():
    for text in ("I want to walk through it", "can I do a walkthrough?"):
        result = classify_scheduling_intent(text)
        assert result.wants_scheduling is True, text
        assert result.kind == "tour", text


def test_viewing_variants_detected_as_tour():
    for text in (
        "I'd like to view the property",
        "can I book a viewing?",
        "interested in a viewing",
    ):
        result = classify_scheduling_intent(text)
        assert result.wants_scheduling is True, text
        assert result.kind == "tour", text


def test_showing_word_detected_as_tour():
    result = classify_scheduling_intent("Is a showing available Saturday?")
    assert result.wants_scheduling is True
    assert result.kind == "tour"
    assert "showing" in result.matched


# --------------------------------------------------------------------------- #
# Positives: inspection signals -> wants_scheduling True, kind == "inspection".
# --------------------------------------------------------------------------- #
def test_inspection_is_detected():
    result = classify_scheduling_intent("set up an inspection")
    assert result.wants_scheduling is True
    assert result.kind == "inspection"
    assert "inspection" in result.matched


def test_inspect_and_inspector_detected_as_inspection():
    for text in ("can the inspector come Tuesday?", "I want to inspect the property"):
        result = classify_scheduling_intent(text)
        assert result.wants_scheduling is True, text
        assert result.kind == "inspection", text


# --------------------------------------------------------------------------- #
# Tie-breaking: both present -> prefer the explicit inspection signal.
# --------------------------------------------------------------------------- #
def test_both_signals_prefers_inspection():
    # "tour" + "inspection" both appear; inspection is the more explicit ask.
    result = classify_scheduling_intent(
        "Can I tour the house and also schedule an inspection?"
    )
    assert result.wants_scheduling is True
    assert result.kind == "inspection"
    # Both surface terms recorded for transparency.
    assert "inspection" in result.matched


# --------------------------------------------------------------------------- #
# Negatives: no scheduling intent -> False, kind None, empty matched.
# --------------------------------------------------------------------------- #
def test_empty_string_is_negative():
    result = classify_scheduling_intent("")
    assert result.wants_scheduling is False
    assert result.kind is None
    assert result.matched == ()


def test_pricing_question_is_negative():
    for text in ("what's it worth?", "is this priced well?", "what's the price?"):
        result = classify_scheduling_intent(text)
        assert result.wants_scheduling is False, text
        assert result.kind is None, text
        assert result.matched == (), text


def test_substring_does_not_false_match():
    # Word-boundary discipline: "contour", "detour", "revisit", "review" must
    # not trip "tour" / "visit" / "view".
    for text in (
        "the contour of the lot is gentle",
        "we took a detour past it",
        "please review the disclosure",
        "I'll revisit my budget later",
    ):
        result = classify_scheduling_intent(text)
        assert result.wants_scheduling is False, text
        assert result.kind is None, text


# --------------------------------------------------------------------------- #
# Case-insensitivity.
# --------------------------------------------------------------------------- #
def test_case_insensitive():
    result = classify_scheduling_intent("CAN I TOUR THIS HOUSE?")
    assert result.wants_scheduling is True
    assert result.kind == "tour"


# --------------------------------------------------------------------------- #
# Fair-Housing safety.
# --------------------------------------------------------------------------- #
def test_protected_class_mention_without_tour_intent_is_negative():
    # A message that mentions a protected class but no scheduling intent must
    # NOT classify as scheduling — no leakage, no keying off the attribute.
    result = classify_scheduling_intent(
        "Is this a good area for a Christian family with young children?"
    )
    assert result.wants_scheduling is False
    assert result.kind is None
    assert result.matched == ()


def test_tour_request_with_protected_term_classifies_on_tour_only():
    # A genuine tour ask that ALSO mentions a protected class still classifies
    # on the tour signal; matched must contain NO protected-class term.
    text = "As a wheelchair user, can I tour this house on Friday?"
    result = classify_scheduling_intent(text)
    assert result.wants_scheduling is True
    assert result.kind == "tour"
    assert "tour" in result.matched
    # The matched terms must leak no protected-class surface term.
    for term in result.matched:
        assert find_protected_terms(term) == [], term


def test_matched_terms_never_contain_protected_attributes():
    # Sweep a few protected mentions alongside tour intent; matched stays clean.
    for text in (
        "We're a married couple — can we see the home?",
        "I'm a senior; I'd like to schedule a showing",
        "single mother of two here, can I book a viewing?",
    ):
        result = classify_scheduling_intent(text)
        assert result.wants_scheduling is True, text
        assert result.kind == "tour", text
        for term in result.matched:
            assert find_protected_terms(term) == [], (text, term)
