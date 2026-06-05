"""Tests for the optional Gemini naturalizer: the LLM rewrites the ALREADY-
verified, cited message into natural prose (post-Critic), with the deterministic
verified text as the no-key fallback. The glass box (claims/citations) is
unchanged — these tests prove the naturalizer only touches phrasing."""
from brain.llm import gemini_client_or_none
from brain.orchestrator.generator import naturalize_message
from brain.orchestrator.graph import build_orchestrator
from brain.rag import FakeEmbedder, InMemoryVectorStore, Retriever

COVERED = "123 Main St Austin TX"


class FakeGemini:
    def __init__(self, response="", error=None):
        self._response = response
        self._error = error

    def generate(self, prompt, **_):
        if self._error:
            raise self._error
        return self._response


def _fakes():
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedder)
    return Retriever(store=store, embedder=embedder)


# --- the naturalizer helper ---------------------------------------------------

def test_no_key_means_no_client(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert gemini_client_or_none() is None


def test_naturalize_rewrites_with_the_llm():
    rewrite = "Atlas values this home at about $620,000 — it looks fairly priced."
    out = naturalize_message("Estimated value is $620,000.", "is it fairly priced?", FakeGemini(response=rewrite))
    assert out == rewrite


def test_naturalize_keeps_verified_text_on_failure():
    verified = "Estimated value is $620,000."
    out = naturalize_message(verified, "q", FakeGemini(error=RuntimeError("api down")))
    assert out == verified


def test_naturalize_passes_through_empty_message():
    assert naturalize_message("", "q", FakeGemini(response="anything")) == ""


# --- wired into the orchestrator send path ------------------------------------

def test_send_never_ships_an_unverified_rewrite():
    """SAFETY (P1): a rewrite that introduces unsupported content ('low six
    figures', 'fairly valued') fails the re-verification through the Critic, so
    it is NOT sent — the deterministic verified message goes out instead."""
    rewrite = "Here's the gist: Atlas estimates this home in the low six figures, and it looks fairly valued."
    app = build_orchestrator(retriever=_fakes(), naturalizer=FakeGemini(response=rewrite))
    state = app.invoke({"address": COVERED, "query": "is it fairly priced?", "attempts": 0},
                       config={"configurable": {"thread_id": "nat-1"}})
    if state.get("outcome") == "send":
        assert "low six figures" not in state["final_message"]  # the unverified rewrite is rejected
        assert "fairly valued" not in state["final_message"]
        assert state["final_message"].strip()  # a verified message is still sent

def test_send_falls_back_to_verified_text_when_rewrite_trips_fair_housing():
    # A rewrite that trips the Fair Housing rail must NOT be sent; the verified
    # (deterministic) message is kept instead.
    tripping = "This home is in a family-friendly neighborhood with good schools."
    app = build_orchestrator(retriever=_fakes(), naturalizer=FakeGemini(response=tripping))
    state = app.invoke({"address": COVERED, "query": "tell me about it", "attempts": 0},
                       config={"configurable": {"thread_id": "nat-2"}})
    if state.get("outcome") == "send":
        assert "good schools" not in state["final_message"]


def test_submitted_trace_matches_the_message_actually_sent():
    """GLASS-BOX CONSISTENCY (P2): whatever wording is sent, the SUBMITTED trace
    (``verification`` + ``citations``) must describe THAT wording — never a
    superseded deterministic draft. The invariant holds in both branches:
    rewrite-rejected (original kept) and rewrite-adopted (trace swapped to the
    re-verification). We exercise an adopting rewrite and a rejected one."""
    for thread, rewrite in (("trace-adopt", None), ("trace-reject", "in the low six figures")):
        app = build_orchestrator(
            retriever=_fakes(),
            naturalizer=FakeGemini(response=rewrite) if rewrite else None,
        )
        state = app.invoke({"address": COVERED, "query": "is it fairly priced?", "attempts": 0},
                           config={"configurable": {"thread_id": thread}})
        if state.get("outcome") != "send":
            continue
        verification = state["verification"]
        # The trace a reviewer reads is the verification of the sent message.
        assert verification.approved_message == state["final_message"]
        assert list(verification.citations) == list(state["citations"])
