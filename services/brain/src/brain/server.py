"""Brain gRPC server.

Serves Valuation and Verification. U1 wires the Valuation servicer to the
placeholder core and a permissive Verification stub so the service boots and the
gateway round-trip works. U3/U6 replace the servicer bodies with the real AVM
and the decompose -> retrieve -> entail -> cite -> score Critic pipeline.
"""
from __future__ import annotations

import os
import threading
from concurrent import futures

import grpc

from genproto.realestate.v1 import realestate_pb2 as pb
from genproto.realestate.v1 import realestate_pb2_grpc as rpc

from brain.closer_service import CloserServicer
from brain.orchestrator import build_orchestrator
from brain.valuation import estimate_value


class ValuationServicer(rpc.ValuationServicer):
    def GetValuation(self, request, context):
        v = estimate_value(request.address)
        return pb.GetValuationResponse(
            sufficient_data=v.sufficient_data,
            estimate=v.estimate,
            low=v.low,
            high=v.high,
            facts=[
                pb.SourceFact(
                    source_id=f.source_id,
                    kind=f.kind,
                    description=f.description,
                    contribution=f.contribution,
                )
                for f in v.facts
            ],
        )


class VerificationServicer(rpc.VerificationServicer):
    """U1 stub: approves with low confidence so nothing ships unverified by
    accident downstream. U6 replaces this with the real Critic pipeline."""

    def VerifyMessage(self, request, context):
        return pb.VerifyMessageResponse(
            approved=False,
            escalate=True,
            confidence=0.0,
            reason="U1 stub: Critic not yet implemented (U6).",
        )


# One compiled orchestrator per process. It owns an in-memory RAG store and a
# MemorySaver checkpointer, so building it once lets a `thread_id` resume a
# multi-turn conversation and lets ingested valuation facts persist across turns.
# Built lazily under a lock (the gRPC server is multi-threaded).
_orchestrator = None
_orchestrator_lock = threading.Lock()


def _get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
            if _orchestrator is None:
                _orchestrator = build_orchestrator()
    return _orchestrator


def _reasoning_steps(state: dict) -> list:
    """Turn the orchestrator's final state into a UI-renderable step timeline.

    One entry per node the loop ran (generate → critique → fair_housing →
    decide), each with a status the UI colours: ok / warn / block.
    """
    verification = state.get("verification")
    fair_housing = state.get("fair_housing")
    decision = state.get("decision")
    sufficient = bool(state.get("sufficient_data", False))

    claims = list(getattr(verification, "claims", []) or [])
    entailed = sum(1 for v in claims if getattr(v, "supported", False))

    steps = []
    steps.append(
        pb.ReasoningStep(
            node="generate",
            title="Retrieve & draft",
            detail=(
                f"Valued the property and grounded a draft from {len(claims)} "
                f"source-backed fact(s)."
                if sufficient
                else "No source coverage for this address — nothing to ground a claim on."
            ),
            status="ok" if sufficient else "warn",
        )
    )
    if verification is not None:
        steps.append(
            pb.ReasoningStep(
                node="critique",
                title="Verify every claim (Critic)",
                detail=(
                    f"{entailed}/{len(claims)} claim(s) entailed by source data and cited. "
                    f"{getattr(verification, 'reason', '')}"
                ),
                status="ok" if getattr(verification, "approved", False) else "block",
            )
        )
    if fair_housing is not None:
        steps.append(
            pb.ReasoningStep(
                node="fair_housing",
                title="Fair Housing wording rail",
                detail=getattr(fair_housing, "reason", ""),
                status="ok" if getattr(fair_housing, "allowed", False) else "block",
            )
        )
    if decision is not None:
        steps.append(
            pb.ReasoningStep(
                node="decide",
                title="Decide & route",
                detail=getattr(decision, "reason", ""),
                status="block" if getattr(decision, "escalated", False) else "ok",
            )
        )
    return steps


class ConversationServicer(rpc.ConversationServicer):
    """Runs one full turn of the LangGraph orchestrator and returns the whole
    reasoning trace, so a UI can show the agent reasoning over live data."""

    def Orchestrate(self, request, context):
        app = _get_orchestrator()
        thread_id = request.thread_id or "anon"
        state = app.invoke(
            {
                "address": request.address,
                "query": request.query,
                "attempts": 0,
            },
            config={"configurable": {"thread_id": thread_id}},
        )

        verification = state.get("verification")
        fair_housing = state.get("fair_housing")
        decision = state.get("decision")
        score = getattr(decision, "score", None)
        signals = getattr(score, "signals", None)
        packet = getattr(decision, "packet", None)

        claims = [
            pb.ReasoningClaim(
                claim=v.claim,
                label=v.label.value,
                score=float(v.score),
                citation_source_id=v.citation or "",
                source_kind=v.source_kind or "",
                supported=bool(v.supported),
                reason=v.reason or "",
            )
            for v in (getattr(verification, "claims", []) or [])
        ]

        return pb.OrchestrateResponse(
            outcome=state.get("outcome", "handoff"),
            escalated=bool(state.get("escalated", True)),
            final_message=state.get("final_message") or "",
            draft=state.get("draft", ""),
            sufficient_data=bool(state.get("sufficient_data", False)),
            attempts=int(state.get("attempts", 0)),
            confidence=float(getattr(score, "score", 0.0)),
            verification_reason=getattr(verification, "reason", ""),
            claims=claims,
            citations=list(state.get("citations", []) or []),
            coverage=float(getattr(signals, "retrieval_coverage", 0.0)),
            agreement=float(getattr(signals, "critic_agreement", 0.0)),
            self_consistency=float(getattr(signals, "self_consistency", 0.0)),
            fair_housing_allowed=bool(getattr(fair_housing, "allowed", True)),
            fair_housing_reason=getattr(fair_housing, "reason", ""),
            handoff_trigger=(packet.trigger.value if packet is not None else ""),
            handoff_reason=(packet.reason if packet is not None else ""),
            handoff_recommended_action=(
                packet.recommended_action if packet is not None else ""
            ),
            hard_trigger=bool(getattr(packet, "hard_trigger", False)),
            steps=_reasoning_steps(state),
        )


def build_server(address: str) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    rpc.add_ValuationServicer_to_server(ValuationServicer(), server)
    rpc.add_VerificationServicer_to_server(VerificationServicer(), server)
    rpc.add_ConversationServicer_to_server(ConversationServicer(), server)
    rpc.add_CloserServicer_to_server(CloserServicer(), server)
    server.add_insecure_port(address)
    return server


def main() -> None:
    address = os.environ.get("BRAIN_BIND", "[::]:50051")
    # Warm the AVM (trains the gradient-boosting model once) before serving so
    # the first GetValuation call isn't slow enough to trip client timeouts.
    estimate_value("warmup")
    # Compile the orchestrator graph once up front so the first Orchestrate call
    # doesn't pay the LangGraph build cost under a client timeout.
    _get_orchestrator()
    server = build_server(address)
    server.start()
    print(f"brain listening on {address}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
