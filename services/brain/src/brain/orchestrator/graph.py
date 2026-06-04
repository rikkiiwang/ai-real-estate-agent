"""The LangGraph orchestrator (U10): generate -> critique -> rail -> decide.

This wires the existing, independently-tested units into one resumable agent
loop, exactly as the KTD prescribes — "LangGraph for agent orchestration now;
Temporal deferred but designed for":

    generate (grounded writer)
        -> critique (U6 Critic: decompose/retrieve/entail/cite/gate)
        -> fair_housing (U7 wording rail)
        -> decide (U8 composite confidence + hard handoff triggers)
        -> {send | regenerate | handoff}

Conditional routing after ``decide``:

* **send** — the Critic approved, the Fair Housing rail allowed, and the draft
  carried at least one supported claim. The cited, approved message is sent and
  the run ends. (END)
* **regenerate** — the Critic blocked because some claims were unsupported but
  others survived (a non-empty ``approved_message``) AND no hard trigger / FH
  trip fired AND we are under the attempt cap. We retry ONCE, re-generating from
  the stripped, already-supported message, then re-critique. Capped at
  ``max_attempts`` (default 2); after the cap it escalates.
* **handoff** — any unfixable block: a contradicted claim, a Fair Housing trip,
  a hard handoff trigger (legal/UPL, high-dollar, hostile, explicit human
  request), a low composite score with nothing to strip, an insufficient-data
  (no-claim) draft, or exhausting the regenerate cap. The handoff packet is
  enqueued via the injected sink and the run ends. (END)

Resumability / durability (KTD): the graph compiles with a checkpointer so an
interrupted run resumes from the persisted state. The DEFAULT is LangGraph's
``MemorySaver`` (in-process, hermetic — no DB, what the tests use). For prod,
pass a ``langgraph.checkpoint.postgres.PostgresSaver`` via ``checkpointer=`` so
the same agent logic survives a process restart against Postgres WITHOUT
reworking any node — and the Closer's longer flows can later migrate to Temporal
behind this same node boundary. We deliberately do NOT require a live Postgres
here.

``build_orchestrator`` takes every collaborator as an injected dependency
(store / embedder / entailer / critic / handoff sink / thresholds) so the whole
graph runs against fakes in tests, with sensible real defaults otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from brain.lawyer.confidence import ConfidenceScore, ConfidenceSignals
from brain.lawyer.critic import (
    DEFAULT_THRESHOLD as CRITIC_DEFAULT_THRESHOLD,
    ClaimVerdict,
    Critic,
    VerificationResult,
)
from brain.lawyer.entailment import Entailer, FakeEntailer, Label
from brain.lawyer.fair_housing import (
    FairHousingMatch,
    FairHousingResult,
    scan_output,
)
from brain.lawyer.handoff import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_HIGH_DOLLAR_BAND,
    Decision,
    FakeHandoffSink,
    HandoffDecision,
    HandoffPacket,
    HandoffSink,
    Trigger,
    decide,
)
from brain.rag import Embedder, FakeEmbedder, InMemoryVectorStore, Retriever, SourceStore

from brain.llm import gemini_client_or_none

from .generator import generate_grounded_draft, naturalize_message
from .state import OrchestratorState

# How many generate passes a single run may make before it must escalate. The
# first pass plus one bounded regenerate = 2 (the KTD's "retry once" cap).
DEFAULT_MAX_ATTEMPTS: int = 2


@dataclass
class _Deps:
    """The injected collaborators a compiled orchestrator closes over."""

    retriever: Retriever
    critic: Critic
    handoff_sink: HandoffSink
    confidence_threshold: float
    high_dollar_band: float
    max_attempts: int
    naturalizer: object = None  # Gemini client when GEMINI_API_KEY is set, else None


# --------------------------------------------------------------------------- #
# Nodes. Each takes the state and returns a partial state dict LangGraph merges.
# --------------------------------------------------------------------------- #
def _make_generate(deps: _Deps):
    def generate(state: OrchestratorState) -> dict:
        """Grounded writer: value the address, ingest facts, compose the draft.

        On a regenerate pass the prior Critic's stripped ``approved_message`` is
        used to seed the draft (unsupported claims already removed). Increments
        ``attempts`` so the loop is bounded.
        """
        attempts = int(state.get("attempts", 0))
        prior = state.get("verification")
        revise_from = None
        if attempts >= 1 and prior is not None:
            # Re-generate from only the supported claims the Critic kept.
            revise_from = getattr(prior, "approved_message", None)

        generated = generate_grounded_draft(
            state["address"], deps.retriever, revise_from=revise_from
        )
        return {
            "draft": generated.draft,
            "sufficient_data": generated.sufficient_data,
            "attempts": attempts + 1,
        }

    return generate


def _make_critique(deps: _Deps):
    def critique(state: OrchestratorState) -> dict:
        """Run the fixed U6 Critic over the current draft."""
        result = deps.critic.verify(state["draft"], address=state.get("address"))
        return {
            "verification": result,
            "citations": list(result.citations),
            "audit_rows": result.audit_rows(),
        }

    return critique


def _make_fair_housing(deps: _Deps):
    def fair_housing(state: OrchestratorState) -> dict:
        """Run the U7 Fair Housing wording rail over the draft (output gate)."""
        return {"fair_housing": scan_output(state.get("draft", ""))}

    return fair_housing


def _make_decide(deps: _Deps):
    def decide_node(state: OrchestratorState) -> dict:
        """Run the U8 composite-confidence + hard-trigger handoff decision.

        The decision itself is computed here; the terminal routing (send vs
        regenerate vs handoff) is chosen by :func:`_route_after_decide` using
        this decision plus the Critic/FH results. The handoff packet is only
        ENQUEUED in the ``handoff`` node, so a run that ends up regenerating or
        sending never spuriously routes a human.
        """
        decision = decide(
            lead_id=state.get("address", "unknown"),
            result=state["verification"],
            fair_housing=state.get("fair_housing"),
            text=state.get("query", ""),
            sink=_NULL_SINK,  # decision-only; real enqueue happens in handoff node
            transcript=state.get("query", ""),
            confidence_threshold=deps.confidence_threshold,
            high_dollar_band=deps.high_dollar_band,
        )
        return {"decision": decision}

    return decide_node


def _make_send(deps: _Deps):
    def send(state: OrchestratorState) -> dict:
        """Terminal: emit a VERIFIED, cited message.

        When a naturalizer (LLM) is configured, it rewrites the already-verified
        message into natural prose — but the rewrite is NEVER sent unverified. It
        is RE-RUN through the SAME Critic (decompose -> retrieve -> entail ->
        cite) and the Fair Housing rail; the rewrite is adopted only if it
        re-verifies to a non-empty, non-escalating, FH-clean message (then its
        citations are used). Otherwise the deterministic verified message is sent.
        So every customer-facing claim is Critic-verified, LLM or not.
        """
        result = state["verification"]
        final = result.approved_message
        citations = list(result.citations)

        if deps.naturalizer is not None and final and final.strip():
            candidate = naturalize_message(final, state.get("query"), deps.naturalizer)
            if candidate and candidate.strip() and candidate.strip() != final.strip():
                recheck = deps.critic.verify(candidate, address=state.get("address"))
                approved = recheck.approved_message
                if (
                    approved
                    and approved.strip()
                    and not recheck.escalate
                    and scan_output(approved).allowed
                ):
                    final = approved  # the re-verified rewrite (stripped to supported claims)
                    citations = list(recheck.citations)

        return {
            "outcome": "send",
            "final_message": final,
            "escalated": False,
            "citations": citations,
        }

    return send


def _make_handoff(deps: _Deps):
    def handoff(state: OrchestratorState) -> dict:
        """Terminal: ALWAYS enqueue a resumable handoff packet via the sink.

        The router routes here for ANY un-sendable outcome — including a Critic
        block (contradicted/baseless claim) or an exhausted regenerate cap that
        the U8 ``decide`` would NOT independently flag (its composite can still
        clear the ops threshold and no hard trigger fired). So this node does not
        merely re-run ``decide`` and hope it escalates: it runs ``decide`` to
        pick up any hard trigger / low-confidence escalation, and if ``decide``
        would have proceeded, it FORCES a handoff packet anyway (the Critic's
        block is itself the reason). Either way exactly one packet is pushed.
        """
        result = state["verification"]
        fh = state.get("fair_housing")
        attempts = int(state.get("attempts", 0))
        capped = attempts >= deps.max_attempts and not getattr(
            result, "approved", False
        )
        extra = ""
        if not state.get("sufficient_data", True):
            extra = " (insufficient source data: no-claim draft, nothing to send)"
        elif capped:
            extra = (
                f" (bounded regenerate exhausted after {deps.max_attempts} "
                f"attempts)"
            )
        recommended = (
            "Human to verify the draft against source data before sending." + extra
        )

        # First, let U8 decide: a hard trigger (legal/UPL, high-dollar, hostile,
        # explicit human request, FH trip) or a low composite enqueues here.
        decision = decide(
            lead_id=state.get("address", "unknown"),
            result=result,
            fair_housing=fh,
            text=state.get("query", ""),
            sink=deps.handoff_sink,
            transcript=state.get("query", ""),
            recommended_action=recommended,
            confidence_threshold=deps.confidence_threshold,
            high_dollar_band=deps.high_dollar_band,
        )

        handoff_id = decision.handoff_id
        if not decision.escalated:
            # The Critic blocked (e.g. a contradicted/baseless claim) but the
            # composite still cleared the ops threshold and no hard trigger
            # fired — ``decide`` would proceed, yet a blocked draft must NEVER
            # send. Force the handoff packet ourselves.
            packet = HandoffPacket(
                lead_id=state.get("address", "unknown"),
                trigger=Trigger.LOW_CONFIDENCE,
                confidence=decision.score.score,
                reason=(
                    "Critic blocked the draft (no clean send path): "
                    f"{getattr(result, 'reason', 'unsupported claim(s)')}{extra}"
                ),
                transcript=state.get("query", ""),
                completed_steps=[
                    f"generated draft (attempt {attempts})",
                    "critique",
                    "fair_housing",
                ],
                retrieved_evidence=list(result.citations),
                recommended_action=recommended,
                hard_trigger=False,
            )
            handoff_id = deps.handoff_sink.push(packet)

        return {
            "outcome": "handoff",
            "final_message": None,
            "escalated": True,
            "decision": decision,
            "handoff_id": handoff_id,
        }

    return handoff


def _default_checkpointer() -> MemorySaver:
    """An in-process MemorySaver that can (de)serialize the Lawyer result types.

    The persisted state holds the Critic / Fair Housing / handoff dataclasses
    and enums from :mod:`brain.lawyer`. LangGraph's msgpack serde requires those
    modules to be allow-listed to round-trip them without a deprecation warning
    (and, in a future LangGraph, at all). We allow the whole ``brain`` namespace
    so any brain result type checkpoints cleanly. Prod swaps this for a
    ``PostgresSaver`` constructed with the same allow-listed serde.
    """
    serde = JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINTED_TYPES)
    return MemorySaver(serde=serde)


# The Lawyer result types that land in the persisted state. Allow-listing the
# concrete classes (not a module prefix) is what the LangGraph msgpack serde
# requires to round-trip them cleanly.
_CHECKPOINTED_TYPES: tuple[type, ...] = (
    Label,
    ClaimVerdict,
    VerificationResult,
    FairHousingMatch,
    FairHousingResult,
    ConfidenceSignals,
    ConfidenceScore,
    Decision,
    Trigger,
    HandoffPacket,
    HandoffDecision,
)


# A no-op sink for the decision-only ``decide`` node (no enqueue there).
class _NullSink:
    def push(self, packet: Any) -> str:  # pragma: no cover - trivial
        return ""


_NULL_SINK = _NullSink()


# --------------------------------------------------------------------------- #
# Conditional routing after ``decide``.
# --------------------------------------------------------------------------- #
def _make_router(deps: _Deps):
    def _route_after_decide(state: OrchestratorState) -> str:
        """Choose the terminal/loop edge: ``send`` | ``regenerate`` | ``handoff``.

        Priority:

        1. A no-claim (insufficient-data) draft never sends -> ``handoff``.
        2. A clean run (Critic approved, FH allowed, decision proceeds, at least
           one supported claim) -> ``send``.
        3. A fixable block (some claims supported and stripped, no contradicted
           claim, no FH trip, no hard trigger, under the attempt cap)
           -> ``regenerate``.
        4. Everything else -> ``handoff``.
        """
        result = state["verification"]
        fh = state.get("fair_housing")
        decision = state["decision"]
        attempts = int(state.get("attempts", 0))

        approved = getattr(result, "approved", False)
        escalated = getattr(decision, "escalated", True)
        fh_allowed = fh is None or getattr(fh, "allowed", False)
        has_supported = any(getattr(v, "supported", False) for v in result.claims)

        # (1) Nothing grounded to send.
        if not state.get("sufficient_data", True) or not result.claims:
            return "handoff"

        # (2) Clean send.
        if approved and not escalated and fh_allowed and has_supported:
            return "send"

        # A Fair Housing trip or a hard handoff trigger is never fixed by
        # stripping claims — escalate straight away.
        fh_tripped = fh is not None and not getattr(fh, "allowed", True)
        hard_trigger = (
            getattr(decision, "escalated", False)
            and getattr(getattr(decision, "packet", None), "hard_trigger", False)
        )
        contradicted = any(v.label is Label.CONTRADICTED for v in result.claims)
        if fh_tripped or hard_trigger or contradicted:
            return "handoff"

        # (3) Bounded regenerate: only worth retrying if some claims survived
        # (a non-empty approved_message) and we are under the cap.
        survivable = bool(getattr(result, "approved_message", None)) and has_supported
        if survivable and attempts < deps.max_attempts:
            return "regenerate"

        # (4) Otherwise escalate.
        return "handoff"

    return _route_after_decide


# --------------------------------------------------------------------------- #
# Builder.
# --------------------------------------------------------------------------- #
def build_orchestrator(
    *,
    store: Optional[SourceStore] = None,
    embedder: Optional[Embedder] = None,
    entailer: Optional[Entailer] = None,
    critic: Optional[Critic] = None,
    handoff_sink: Optional[HandoffSink] = None,
    retriever: Optional[Retriever] = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    critic_threshold: float = CRITIC_DEFAULT_THRESHOLD,
    high_dollar_band: float = DEFAULT_HIGH_DOLLAR_BAND,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    checkpointer: Optional[Any] = None,
    naturalizer: object = None,
):
    """Build and compile the orchestrator graph with injected dependencies.

    Every collaborator is optional and dependency-injected so the whole graph
    runs against fakes in tests; sensible REAL defaults are constructed when an
    argument is omitted:

    * ``embedder`` -> :class:`~brain.rag.FakeEmbedder` (deterministic, no net).
    * ``store`` -> :class:`~brain.rag.InMemoryVectorStore` over that embedder.
    * ``retriever`` -> :class:`~brain.rag.Retriever` over store + embedder.
    * ``entailer`` -> :class:`~brain.lawyer.entailment.FakeEntailer`.
    * ``critic`` -> :class:`~brain.lawyer.critic.Critic` over retriever+entailer.
    * ``handoff_sink`` -> :class:`~brain.lawyer.handoff.FakeHandoffSink`.

    (The fakes are the safe defaults — a real deployment injects the pgvector
    store, a real embedder/entailer, and a ``DomainGrpcHandoffSink``.)

    ``checkpointer`` defaults to a :class:`~langgraph.checkpoint.memory.MemorySaver`
    (hermetic). For prod resumability across a process restart, pass a
    ``langgraph.checkpoint.postgres.PostgresSaver`` instead — the agent logic is
    unchanged. A ``thread_id`` in the invoke ``config`` keys the persisted run.

    Returns the compiled LangGraph app; call ``app.invoke(initial_state,
    config={"configurable": {"thread_id": ...}})`` and read back persisted state
    with ``app.get_state(config)``.
    """
    embedder = embedder or FakeEmbedder()
    store = store or InMemoryVectorStore(embedder)
    retriever = retriever or Retriever(store=store, embedder=embedder)
    entailer = entailer or FakeEntailer()
    critic = critic or Critic(
        retriever=retriever, entailer=entailer, threshold=critic_threshold
    )
    handoff_sink = handoff_sink or FakeHandoffSink()

    deps = _Deps(
        retriever=retriever,
        critic=critic,
        handoff_sink=handoff_sink,
        confidence_threshold=confidence_threshold,
        high_dollar_band=high_dollar_band,
        max_attempts=max_attempts,
        # The LLM only naturalizes the already-verified message (post-Critic); it
        # never affects retrieval/entailment, so the glass box is unchanged. None
        # without GEMINI_API_KEY -> the deterministic message is sent as-is.
        naturalizer=naturalizer or gemini_client_or_none(),
    )

    graph: StateGraph = StateGraph(OrchestratorState)
    graph.add_node("generate", _make_generate(deps))
    graph.add_node("critique", _make_critique(deps))
    graph.add_node("fair_housing", _make_fair_housing(deps))
    graph.add_node("decide", _make_decide(deps))
    graph.add_node("send", _make_send(deps))
    graph.add_node("handoff", _make_handoff(deps))

    graph.add_edge(START, "generate")
    graph.add_edge("generate", "critique")
    graph.add_edge("critique", "fair_housing")
    graph.add_edge("fair_housing", "decide")
    graph.add_conditional_edges(
        "decide",
        _make_router(deps),
        {
            "send": "send",
            "regenerate": "generate",  # bounded loop back to the writer
            "handoff": "handoff",
        },
    )
    graph.add_edge("send", END)
    graph.add_edge("handoff", END)

    # Default checkpointer: in-process MemorySaver (hermetic, no DB). Prod swaps
    # in a PostgresSaver via the ``checkpointer=`` arg for restart-durable runs.
    checkpointer = checkpointer or _default_checkpointer()
    return graph.compile(checkpointer=checkpointer)
