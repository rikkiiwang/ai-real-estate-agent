"""Orchestrator graph state (U10).

The LangGraph state is a ``TypedDict`` threaded through every node: each node
reads the keys it needs and returns a partial dict that LangGraph merges back
in. Keeping it a plain ``TypedDict`` (not a dataclass) is what LangGraph's
``StateGraph`` expects and what its checkpointer serializes between steps, so an
interrupted run resumes from exactly these fields.

The flow that fills it: ``generate`` writes ``draft`` (grounded against the RAG
store); ``critique`` writes ``verification``; ``fair_housing`` writes
``fair_housing``; ``decide`` writes ``decision`` + ``outcome``; the terminal
``send`` / ``handoff`` nodes write ``final_message`` / ``escalated``.
``attempts`` counts generate passes so the bounded-regenerate loop can cap
itself.
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict


class OrchestratorState(TypedDict, total=False):
    """The resumable state threaded through the orchestrator graph.

    All keys are optional (``total=False``) because nodes fill them
    incrementally; the checkpointer persists whatever has been written so far,
    which is what lets a run resume mid-graph.

    * ``address`` — the property the run is about (scopes RAG retrieval).
    * ``query`` — the customer-facing request that kicked off the run.
    * ``draft`` — the current candidate message the Critic verifies.
    * ``verification`` — the U6 :class:`~brain.lawyer.critic.VerificationResult`.
    * ``fair_housing`` — the U7 ``FairHousingResult`` over the draft wording.
    * ``decision`` — the U8 :class:`~brain.lawyer.handoff.HandoffDecision`.
    * ``outcome`` — terminal label: ``"send"`` or ``"handoff"``.
    * ``final_message`` — the cited message actually sent (``None`` on handoff).
    * ``escalated`` — ``True`` iff the run routed to a human.
    * ``handoff_id`` — the sink's id for an enqueued handoff (else ``None``).
    * ``attempts`` — number of generate passes so far (bounded-regenerate cap).
    * ``sufficient_data`` — whether the valuation had ingested coverage.
    * ``citations`` — source ids cited by the sent message (audit trail).
    * ``audit_rows`` — the Critic's per-claim audit rows (for the U9 store).
    """

    address: str
    query: str
    draft: str
    verification: Any
    fair_housing: Any
    decision: Any
    outcome: str
    final_message: Optional[str]
    escalated: bool
    handoff_id: Optional[str]
    attempts: int
    sufficient_data: bool
    citations: list[str]
    audit_rows: list[dict]
