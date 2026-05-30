"""U10 tests — the LangGraph orchestrator wiring (deterministic, no network).

Covers R14. The orchestrator ties the grounded generator to the U6 Critic and
the U7/U8 Lawyer rails as one resumable agent loop:

    generate -> critique -> fair_housing -> decide -> {send | regenerate | handoff}

Every collaborator is a hermetic fake (``InMemoryVectorStore`` + ``FakeEmbedder``
+ ``FakeEntailer`` + ``FakeHandoffSink``) and the graph is checkpointed with a
``MemorySaver`` — no network, no Postgres.

Scenarios:

* HAPPY — a grounded valuation query flows generate -> critique -> send with
  citations and never touches the handoff sink.
* CRITICAL — a draft carrying an unsupported/contradicted (injected) claim NEVER
  sends; it escalates to the handoff sink.
* FAIR HOUSING — a draft that trips the wording rail escalates (FH trigger).
* BOUNDED REGENERATE — a strippable unsupported claim is removed and the run
  proceeds on the retry (or escalates once the attempt cap is hit).
* RESUMABILITY — the run is checkpointed: after ``invoke`` with a ``thread_id``,
  ``get_state`` returns the persisted terminal state.
"""
from __future__ import annotations

import brain.orchestrator.graph as graph_module
from brain.lawyer.decompose import decompose
from brain.lawyer.entailment import FakeEntailer, Label
from brain.lawyer.handoff import FakeHandoffSink, Trigger
from brain.orchestrator import build_orchestrator
from brain.orchestrator.generator import (
    GeneratedDraft,
    generate_grounded_draft,
)
from brain.rag import FakeEmbedder, InMemoryVectorStore, Retriever

# Addresses with ingested coverage (the AVM returns sufficient_data=True). An
# uncovered marker ("nowhere") returns sufficient_data=False.
COVERED = "123 Main St Austin TX"
COVERED_2 = "456 Oak Ave"
COVERED_3 = "789 Pine Rd Austin"
UNCOVERED = "nowhere"


def _fakes():
    """A fresh hermetic dependency set (store/embedder/retriever/sink)."""
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedder)
    retriever = Retriever(store=store, embedder=embedder)
    sink = FakeHandoffSink()
    return embedder, store, retriever, sink


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


# --------------------------------------------------------------------------- #
# Generator (the grounded writer the Critic verifies).
# --------------------------------------------------------------------------- #
def test_generator_ingests_facts_and_grounds_the_draft():
    """The generator values the address, ingests facts, and the draft is grounded.

    Every sentence in the draft must trace to a fact now in the store, so a
    Retriever finds support for each claim (grounded by construction).
    """
    _embedder, store, retriever, _sink = _fakes()
    assert len(store) == 0

    generated = generate_grounded_draft(COVERED, retriever)

    assert generated.sufficient_data is True
    assert generated.draft.strip()
    # Facts were ingested (estimate + per-feature) and the headline number is in
    # the draft.
    assert len(store) > 0
    assert "Estimated value" in generated.draft
    # Each decomposed claim has at least one supporting source in the store.
    for claim in decompose(generated.draft):
        assert retriever.has_support(claim.text, address=COVERED), claim.text


def test_generator_insufficient_data_makes_a_no_claim_draft():
    """An uncovered address yields a no-claim draft and ingests nothing grounded."""
    _embedder, store, retriever, _sink = _fakes()
    generated = generate_grounded_draft(UNCOVERED, retriever)

    assert generated.sufficient_data is False
    # No valuation-run facts were ingested for an uncovered address.
    assert len(store) == 0
    # The Critic must find no grounded claim to (wrongly) approve.
    assert "don't yet have enough" in generated.draft


# --------------------------------------------------------------------------- #
# HAPPY PATH — generate -> critique -> send with citations, no handoff.
# --------------------------------------------------------------------------- #
def test_happy_path_grounded_query_sends_with_citations():
    _embedder, _store, retriever, sink = _fakes()
    app = build_orchestrator(retriever=retriever, handoff_sink=sink)

    out = app.invoke(
        {"address": COVERED, "query": "What is my home worth?", "attempts": 0},
        config=_cfg("happy"),
    )

    assert out["outcome"] == "send"
    assert out["escalated"] is False
    assert out["final_message"] and "Estimated value" in out["final_message"]
    assert out["citations"], "a sent message must carry citations"
    # The grounded happy path never routes a human.
    assert sink.packets == []


# --------------------------------------------------------------------------- #
# CRITICAL — an unsupported/injected claim NEVER sends; it escalates.
# --------------------------------------------------------------------------- #
def test_injected_unsupported_claim_never_sends_and_escalates():
    """A contradicted (injected) claim blocks the send and routes to the sink.

    We inject by pinning the headline estimate claim to CONTRADICTED via a
    FakeEntailer fixture — modelling an entailer that rejects a claim the
    generator made. The draft must NOT send; a handoff packet must be enqueued.
    """
    _embedder, _store, retriever, sink = _fakes()
    # Discover the draft's claims so we can pin one as contradicted.
    draft = generate_grounded_draft(COVERED_2, Retriever(
        store=InMemoryVectorStore(FakeEmbedder()), embedder=FakeEmbedder()
    )).draft
    estimate_claim = _norm(decompose(draft)[0].text)
    entailer = FakeEntailer(fixtures={estimate_claim: Label.CONTRADICTED})

    app = build_orchestrator(
        retriever=retriever, entailer=entailer, handoff_sink=sink
    )
    out = app.invoke(
        {"address": COVERED_2, "query": "value?", "attempts": 0},
        config=_cfg("contradicted"),
    )

    assert out["outcome"] == "handoff"
    assert out["escalated"] is True
    assert out["final_message"] is None
    assert len(sink.packets) == 1


def test_insufficient_data_query_never_sends_and_escalates():
    """An uncovered address produces a no-claim draft -> handoff, never a number."""
    _embedder, _store, retriever, sink = _fakes()
    app = build_orchestrator(retriever=retriever, handoff_sink=sink)

    out = app.invoke(
        {"address": UNCOVERED, "query": "value?", "attempts": 0},
        config=_cfg("insufficient"),
    )

    assert out["outcome"] == "handoff"
    assert out["escalated"] is True
    assert out["final_message"] is None
    assert len(sink.packets) == 1


# --------------------------------------------------------------------------- #
# FAIR HOUSING — a wording-rail trip escalates.
# --------------------------------------------------------------------------- #
def test_fair_housing_trip_escalates(monkeypatch):
    """A draft that trips the FH wording rail routes to handoff (FH trigger).

    The real generator pre-screens its sentences through the SAME rail, so it
    never emits tripping wording; to exercise the rail NODE we substitute a
    generator that emits a steering proxy ("good schools").
    """
    _embedder, _store, retriever, sink = _fakes()

    def tripping_generator(address, retriever, *, condition=None, revise_from=None):
        return GeneratedDraft(
            draft="This home is in a neighborhood with good schools.",
            sufficient_data=True,
            run_id="run",
        )

    monkeypatch.setattr(
        graph_module, "generate_grounded_draft", tripping_generator
    )

    app = build_orchestrator(retriever=retriever, handoff_sink=sink)
    out = app.invoke(
        {"address": COVERED, "query": "tell me about the area", "attempts": 0},
        config=_cfg("fh"),
    )

    assert out["outcome"] == "handoff"
    assert out["escalated"] is True
    assert out["fair_housing"].allowed is False
    assert len(sink.packets) == 1
    assert sink.packets[0].trigger is Trigger.FAIR_HOUSING


# --------------------------------------------------------------------------- #
# BOUNDED REGENERATE.
# --------------------------------------------------------------------------- #
def test_bounded_regenerate_strips_unsupported_claim_then_sends():
    """A strippable (baseless) claim is removed; the retry sends the rest.

    A BASELESS-pinned non-headline claim is stripped from the approved message;
    the bounded regenerate re-generates from that stripped message and the
    second pass sends (no contradiction, no FH trip). attempts must reach 2.
    """
    _embedder, _store, retriever, sink = _fakes()
    draft = generate_grounded_draft(COVERED_3, Retriever(
        store=InMemoryVectorStore(FakeEmbedder()), embedder=FakeEmbedder()
    )).draft
    claims = decompose(draft)
    strip_claim = _norm(claims[2].text)  # a non-headline feature claim
    entailer = FakeEntailer(fixtures={strip_claim: Label.BASELESS})

    app = build_orchestrator(
        retriever=retriever, entailer=entailer, handoff_sink=sink
    )
    out = app.invoke(
        {"address": COVERED_3, "query": "value?", "attempts": 0},
        config=_cfg("regen"),
    )

    assert out["outcome"] == "send"
    assert out["escalated"] is False
    assert out["attempts"] == 2  # first pass + one bounded regenerate
    assert "Estimated value" in out["final_message"]
    # The stripped claim is gone from the sent message.
    assert claims[2].text.rstrip(".") not in out["final_message"]
    assert sink.packets == []


def test_regenerate_cap_escalates_when_block_persists():
    """When every pass is blocked, the run escalates after the attempt cap.

    A FakeEntailer that returns BASELESS for *every* claim (empty fixtures +
    impossible overlap threshold) leaves no supported claim to send and no
    survivable message to regenerate from, so the run escalates with exactly one
    handoff packet rather than looping forever.
    """
    _embedder, _store, retriever, sink = _fakes()
    # entail_threshold > 1.0 -> no claim ever reaches the entail bar -> BASELESS.
    entailer = FakeEntailer(entail_threshold=2.0)

    app = build_orchestrator(
        retriever=retriever, entailer=entailer, handoff_sink=sink, max_attempts=2
    )
    out = app.invoke(
        {"address": COVERED, "query": "value?", "attempts": 0},
        config=_cfg("cap"),
    )

    assert out["outcome"] == "handoff"
    assert out["escalated"] is True
    assert out["final_message"] is None
    assert len(sink.packets) == 1
    # Bounded: it did not loop past the cap.
    assert out["attempts"] <= 2


# --------------------------------------------------------------------------- #
# RESUMABILITY — the run is checkpointed.
# --------------------------------------------------------------------------- #
def test_run_is_checkpointed_and_state_persists():
    """After invoke with a thread_id, get_state returns the persisted state.

    This is the resumability contract (MemorySaver + thread_id config): the
    terminal state survives in the checkpointer keyed by the thread, so an
    interrupted run resumes from it.
    """
    _embedder, _store, retriever, sink = _fakes()
    app = build_orchestrator(retriever=retriever, handoff_sink=sink)
    cfg = _cfg("persist")

    out = app.invoke(
        {"address": COVERED, "query": "What is my home worth?", "attempts": 0},
        config=cfg,
    )

    snapshot = app.get_state(cfg)
    assert snapshot.values["outcome"] == out["outcome"] == "send"
    assert snapshot.values["final_message"] == out["final_message"]
    assert snapshot.values["address"] == COVERED
    # A distinct thread has no persisted state.
    empty = app.get_state(_cfg("never-run"))
    assert empty.values == {}


def test_default_build_uses_real_defaults_and_runs():
    """build_orchestrator with NO injected deps wires real fakes and runs.

    Confirms the sensible-defaults path (FakeEmbedder/InMemoryVectorStore/
    Retriever/FakeEntailer/Critic/FakeHandoffSink + MemorySaver) compiles and
    produces a terminal outcome without any arguments.
    """
    app = build_orchestrator()
    out = app.invoke(
        {"address": COVERED, "query": "value?", "attempts": 0},
        config=_cfg("defaults"),
    )
    assert out["outcome"] in {"send", "handoff"}
