"""Scheduling-intent classifier — the brain's small, honest, LLM-free capability.

It recognizes "I want to tour / see / visit / book a viewing / set up an
inspection" from neutral phrasing so the agent can route to the (Rails-owned)
collision-aware slots UI. It is the canonical capability the spec (R6 §6)
promises; the Rails-side ``ShowingIntent`` matcher mirrors this word list at
runtime.

Design (deterministic, stdlib only):
- Word-boundary regexes so substrings never false-match ("contour" ≠ tour,
  "review" ≠ view, "revisit" ≠ visit).
- ``matched`` records canonical signal tokens (never the raw surface text), so
  it can never leak a protected-class term — honoring the same Fair-Housing
  neutral-field discipline as ``buyer_intake``. The classifier keys ONLY on
  tour/inspection intent and is blind to protected attributes.
- Tie-break: when both a tour and an inspection signal appear, the more explicit
  ``inspection`` wins.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SchedulingIntent:
    """Result of classifying a message for scheduling intent.

    ``wants_scheduling`` is True iff any tour/inspection signal matched.
    ``kind`` is ``"tour"`` | ``"inspection"`` | ``None``. ``matched`` holds the
    canonical signal tokens that fired (deterministic order, deduped) — never the
    raw surface text, so it carries no protected-class terms.
    """

    wants_scheduling: bool
    kind: Optional[str]
    matched: tuple[str, ...]


# (canonical token, kind, compiled pattern). Order is the deterministic order in
# which ``matched`` is reported. Patterns are word-boundary anchored so common
# substrings ("contour", "detour", "review", "revisit") never trip a signal.
_SIGNALS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("tour", "tour", re.compile(r"\btour(s|ing|ed)?\b", re.IGNORECASE)),
    ("showing", "tour", re.compile(r"\bshowing\b", re.IGNORECASE)),
    ("visit", "tour", re.compile(r"\bvisit(s|ing|ed)?\b", re.IGNORECASE)),
    ("walkthrough", "tour", re.compile(r"\bwalk\s*through\b", re.IGNORECASE)),
    ("viewing", "tour", re.compile(r"\bview(ing|ed|s)?\b", re.IGNORECASE)),
    ("see", "tour", re.compile(r"\bsee the (house|home|place)\b", re.IGNORECASE)),
    ("inspection", "inspection", re.compile(r"\binspection\b", re.IGNORECASE)),
    ("inspector", "inspection", re.compile(r"\binspector\b", re.IGNORECASE)),
    ("inspect", "inspection", re.compile(r"\binspect\b", re.IGNORECASE)),
)


def classify_scheduling_intent(text: str) -> SchedulingIntent:
    """Classify ``text`` for tour/inspection scheduling intent.

    Returns a :class:`SchedulingIntent`. Pure and deterministic — no network, no
    LLM, no state. Reads only scheduling intent; blind to protected attributes.
    """
    if not text:
        return SchedulingIntent(wants_scheduling=False, kind=None, matched=())

    matched: list[str] = []
    kinds: set[str] = set()
    for token, kind, pattern in _SIGNALS:
        if pattern.search(text):
            matched.append(token)
            kinds.add(kind)

    if not matched:
        return SchedulingIntent(wants_scheduling=False, kind=None, matched=())

    # Tie-break: an explicit inspection ask wins over a co-occurring tour ask.
    kind = "inspection" if "inspection" in kinds else "tour"
    return SchedulingIntent(wants_scheduling=True, kind=kind, matched=tuple(matched))


__all__ = ["SchedulingIntent", "classify_scheduling_intent"]
