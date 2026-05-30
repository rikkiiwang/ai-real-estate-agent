"""The orchestrator (U10): the LangGraph agent loop wiring the Brain together.

Ties the independently-built units into one resumable agent flow —
``generate -> critique -> fair_housing -> decide -> {send | regenerate |
handoff}`` — with the U6 Critic and U7/U8 Lawyer rails as gates and a grounded
generator the Critic can actually verify. See :mod:`brain.orchestrator.graph`
for the wiring and ``build_orchestrator`` for the injectable entry point.

KTD: LangGraph now (conditional edges + a checkpointer for resumability),
Temporal deferred but designed for — the node boundaries are the seam a durable
backend slots behind without reworking the agent logic.
"""
from __future__ import annotations

from .generator import GeneratedDraft, generate_grounded_draft
from .graph import DEFAULT_MAX_ATTEMPTS, build_orchestrator
from .state import OrchestratorState

__all__ = [
    "OrchestratorState",
    "GeneratedDraft",
    "generate_grounded_draft",
    "build_orchestrator",
    "DEFAULT_MAX_ATTEMPTS",
]
