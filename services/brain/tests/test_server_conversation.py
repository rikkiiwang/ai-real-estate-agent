"""Tests for the Conversation gRPC servicer (the chat agent's edge).

The servicer runs one full turn of the LangGraph orchestrator and maps its
final state onto the rich ``OrchestrateResponse`` the chat UI renders — the
grounded answer, the per-claim verdicts + citations, the composite-confidence
sub-signals, the Fair Housing decision, and (on escalation) the handoff trigger.

These run the REAL orchestrator with its hermetic in-memory defaults
(FakeEmbedder + InMemoryVectorStore + FakeEntailer + MemorySaver) — no network,
no Postgres — and assert the three demo-critical outcomes:

* GROUNDED  — a covered address returns ``send`` with citations + a reasoning
  trail whose every step is ``ok``.
* UNKNOWN   — an address with no coverage escalates (the "no source -> no claim"
  safety rail), never inventing a number.
* HARD TRIGGER — a request for custom clause language escalates regardless of
  confidence (legal/UPL), proving the hard handoff trigger overrides the score.
"""
from __future__ import annotations

from brain.server import ConversationServicer
from genproto.realestate.v1 import realestate_pb2 as pb


def _run(address: str, query: str, thread_id: str):
    svc = ConversationServicer()
    req = pb.OrchestrateRequest(address=address, query=query, thread_id=thread_id)
    return svc.Orchestrate(req, None)


def test_grounded_query_sends_with_citations_and_reasoning_trail():
    r = _run("123 Main St, Austin TX 78701", "What is my home worth and why?", "t-send")

    assert r.outcome == "send"
    assert r.escalated is False
    assert r.sufficient_data is True
    assert r.final_message and "Estimated value" in r.final_message
    assert list(r.citations), "a sent message must carry citations"
    assert r.confidence >= 0.6

    # Every claim that backs the message is entailed AND cited.
    assert r.claims
    supported = [c for c in r.claims if c.supported]
    assert supported, "expected at least one supported, cited claim"
    assert all(c.label == "ENTAILED" for c in supported)
    assert all(c.citation_source_id for c in supported)

    # The reasoning timeline covers the whole loop and is clean.
    nodes = [s.node for s in r.steps]
    assert nodes == ["generate", "critique", "fair_housing", "decide"]
    assert all(s.status == "ok" for s in r.steps)
    assert r.fair_housing_allowed is True


def test_unknown_address_escalates_rather_than_inventing():
    r = _run("nowhere-zzz-unknown", "What is my home worth?", "t-handoff")

    assert r.outcome == "handoff"
    assert r.escalated is True
    assert r.sufficient_data is False
    assert r.final_message == "", "an escalated turn sends no customer message"
    assert r.handoff_trigger  # a trigger label is recorded
    assert r.handoff_recommended_action


def test_legal_clause_request_hits_hard_trigger():
    r = _run(
        "123 Main St, Austin TX 78701",
        "Can you add a custom indemnification clause to my contract?",
        "t-legal",
    )

    assert r.outcome == "handoff"
    assert r.escalated is True
    assert r.handoff_trigger == "legal_complexity_upl"
    assert r.hard_trigger is True
