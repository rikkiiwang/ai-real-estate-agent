"""Human-in-the-loop handoff (U8) — hard triggers + the escalation decision.

Management-by-exception: most messages flow through the Critic (U6) and Fair
Housing rail (U7) and proceed. The exceptions are routed to a human with FULL,
resumable context. Two layers decide an exception:

1. **HARD-CODED, non-model-adjustable triggers** that FORCE a handoff regardless
   of the composite confidence score (so a *confidently* wrong / out-of-scope
   move still escalates):

   * **legal complexity / UPL** — a request for a custom contract clause or
     legal advice (keyword/intent detection). The agent never practices law.
   * **high dollar value / binding commitment** — a transaction amount above a
     configurable band, or language that binds the principal.
   * **hostile / distressed or FH-sensitive sentiment** — keyword/intent detect.
   * **a Fair Housing rail trip** — a :class:`FairHousingResult` that escalated.
   * **explicit "I want a human"** — the consumer asked for a person.

   These are *data + deterministic detectors*, deliberately not tunable by a
   model or by ops.

2. **Ops-tunable confidence threshold** — BELOW the hard triggers. A low
   composite confidence (:mod:`brain.lawyer.confidence`) also escalates, but a
   hard trigger fires even at HIGH confidence.

On escalation, :func:`decide` packages a :class:`HandoffPacket` carrying the
trigger, score, reason, transcript, completed steps, retrieved evidence, and a
recommended action, and pushes it to an injected :class:`HandoffSink`.

Sinks:

* :class:`FakeHandoffSink` — records packets in memory (for tests / dry runs).
* :class:`DomainGrpcHandoffSink` — maps the packet to the proto
  ``HandoffPacket`` and calls ``Domain.EnqueueHandoff`` (U9). It is IMPORT-SAFE
  and constructs WITHOUT connecting: the gRPC channel/stub are created lazily on
  first :meth:`push`, never at import or construction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Protocol

from .confidence import ConfidenceScore, composite_confidence
from .critic import VerificationResult
from .fair_housing import FairHousingResult

# --------------------------------------------------------------------------- #
# Configurable ops band (above the model, but below the hard triggers' intent:
# these are deployment settings, not model-adjustable per-message). The HARD
# trigger *detectors* below are NOT tunable.
# --------------------------------------------------------------------------- #

# Ops-tunable confidence floor: a composite below this escalates (a low score is
# a soft trigger). Hard triggers fire even ABOVE it.
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.6

# Configurable high-dollar band: a transaction amount at/above this forces a
# handoff (binding commitment / high financial stakes).
DEFAULT_HIGH_DOLLAR_BAND: float = 100_000.0


class Trigger(str, Enum):
    """Why a handoff fired — a stable, loggable label.

    The first five are HARD triggers (force handoff regardless of score). The
    last is the soft, ops-tunable confidence trigger.
    """

    LEGAL_UPL = "legal_complexity_upl"
    HIGH_DOLLAR = "high_dollar_value"
    HOSTILE_SENTIMENT = "hostile_or_distressed_sentiment"
    FAIR_HOUSING = "fair_housing_rail_trip"
    HUMAN_REQUEST = "explicit_human_request"
    LOW_CONFIDENCE = "low_confidence"

    @property
    def is_hard(self) -> bool:
        """True for the non-model-adjustable triggers that override the score."""
        return self is not Trigger.LOW_CONFIDENCE


class Decision(str, Enum):
    """The routing outcome for a message."""

    PROCEED = "proceed"
    ESCALATE = "escalate"


# --------------------------------------------------------------------------- #
# Hard-trigger detectors — DATA + deterministic regex. NOT model/ops adjustable.
# --------------------------------------------------------------------------- #

# Legal complexity / UPL: requests for custom clause language or legal advice.
_LEGAL_UPL_PATTERNS: tuple[str, ...] = (
    r"\bcustom\b.{0,20}\bclause\b",
    r"\bclause\b.{0,20}\b(add|insert|include|draft|write|change|modify)\b",
    r"\b(add|insert|include|draft|write|change|modify)\b.{0,20}\bclause\b",
    r"\bcontingency\b.{0,20}\b(clause|language|wording)\b",
    r"\b(special|additional|non-standard|nonstandard)\b.{0,20}\b(provision|clause|term|language)\b",
    r"\blegal advice\b",
    r"\bis (this|it) legally (binding|enforceable)\b",
    r"\bcan you (write|draft|add).{0,30}\b(clause|provision|addendum|amendment)\b",
    r"\bre-?word\b.{0,20}\b(contract|clause|provision)\b",
)

# Hostile / distressed / FH-sensitive sentiment.
_HOSTILE_PATTERNS: tuple[str, ...] = (
    r"\b(furious|outraged|outrage|enraged|livid|disgust(ed|ing)?)\b",
    r"\b(scam|scammer|fraud|fraudulent|cheat(ed|ing)?|rip(ped)?[ -]?off)\b",
    r"\b(sue|suing|lawsuit|lawyer up|attorney)\b",
    r"\b(threaten|threatening|hate you|shut up|stupid)\b",
    r"\bthis is (ridiculous|unacceptable|outrageous)\b",
    # Distressed signals.
    r"\b(foreclosure|foreclosing|evict(ed|ion)?|bankrupt(cy)?|desperate|emergency)\b",
    r"\b(losing (my|our) home|about to lose)\b",
)

# Explicit "I want a human".
_HUMAN_REQUEST_PATTERNS: tuple[str, ...] = (
    r"\b(speak|talk|connect me|put me through)\b.{0,20}\b(a )?(human|person|agent|representative|rep|broker|someone real)\b",
    r"\b(want|need|get me|give me)\b.{0,20}\b(a )?(human|real person|live agent|real agent|real estate agent)\b",
    r"\breal (human|person)\b",
    r"\bstop (talking to|using) (a )?(bot|robot|ai)\b",
    r"\bare you (a )?(bot|robot|ai|human|real)\b",
)

_LEGAL_UPL_RE = re.compile("|".join(_LEGAL_UPL_PATTERNS), re.IGNORECASE)
_HOSTILE_RE = re.compile("|".join(_HOSTILE_PATTERNS), re.IGNORECASE)
_HUMAN_REQUEST_RE = re.compile("|".join(_HUMAN_REQUEST_PATTERNS), re.IGNORECASE)


def detect_legal_upl(text: str) -> bool:
    """True if ``text`` requests custom clause language / legal advice (UPL)."""
    return bool(_LEGAL_UPL_RE.search(text or ""))


def detect_hostile_sentiment(text: str) -> bool:
    """True if ``text`` reads as hostile, distressed, or FH-sensitive."""
    return bool(_HOSTILE_RE.search(text or ""))


def detect_human_request(text: str) -> bool:
    """True if ``text`` explicitly asks to reach a human."""
    return bool(_HUMAN_REQUEST_RE.search(text or ""))


# --------------------------------------------------------------------------- #
# The structured handoff packet (resumable context for the broker dashboard).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HandoffPacket:
    """Everything a human needs to resume an escalated exchange (loggable).

    ``lead_id`` ties it to the CRM lead. ``trigger`` is the (first) firing
    :class:`Trigger`. ``confidence`` is the composite score at decision time.
    ``reason`` is the human-readable audit line. ``transcript`` is the
    conversation so far. ``completed_steps`` are the actions already taken
    (resumability). ``retrieved_evidence`` are the source ids the Critic cited.
    ``recommended_action`` is what the agent suggests the human do.
    ``hard_trigger`` records whether a non-model-adjustable trigger fired.
    """

    lead_id: str
    trigger: Trigger
    confidence: float
    reason: str
    transcript: str
    completed_steps: List[str] = field(default_factory=list)
    retrieved_evidence: List[str] = field(default_factory=list)
    recommended_action: str = ""
    hard_trigger: bool = False

    def to_dict(self) -> dict:
        """Plain-dict view for the audit store / debugging."""
        return {
            "lead_id": self.lead_id,
            "trigger": self.trigger.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "transcript": self.transcript,
            "completed_steps": list(self.completed_steps),
            "retrieved_evidence": list(self.retrieved_evidence),
            "recommended_action": self.recommended_action,
            "hard_trigger": self.hard_trigger,
        }


# --------------------------------------------------------------------------- #
# Sinks.
# --------------------------------------------------------------------------- #
class HandoffSink(Protocol):
    """Where a :class:`HandoffPacket` is pushed (injected, so tests use a fake).

    Implementations return an opaque handoff id (or ``""`` if not applicable).
    """

    def push(self, packet: HandoffPacket) -> str:  # pragma: no cover - protocol
        ...


@dataclass
class FakeHandoffSink:
    """An in-memory sink that records packets — for tests and dry runs.

    Performs NO network I/O. Inspect :attr:`packets` to assert what was routed.
    """

    packets: List[HandoffPacket] = field(default_factory=list)

    def push(self, packet: HandoffPacket) -> str:
        """Record ``packet`` and return a synthetic handoff id."""
        self.packets.append(packet)
        return f"fake-handoff-{len(self.packets)}"


class DomainGrpcHandoffSink:
    """Push handoff packets to Rails' ``Domain.EnqueueHandoff`` over gRPC (U9).

    IMPORT-SAFE and connection-free at construction: the channel and stub are
    created LAZILY on the first :meth:`push`, never at import or in
    ``__init__``. This keeps importing :mod:`brain.lawyer.handoff` (and
    constructing the sink in tests) free of any network dependency.
    """

    def __init__(self, target: str = "localhost:50051") -> None:
        """Store the dial ``target`` only; do NOT open a channel here."""
        self._target = target
        self._channel = None  # lazily created grpc.Channel
        self._stub = None  # lazily created DomainStub

    def _ensure_stub(self):
        """Create the channel + stub on first use (lazy connect)."""
        if self._stub is None:
            import grpc  # imported lazily so import of this module needs no grpc

            from genproto.realestate.v1 import realestate_pb2_grpc

            self._channel = grpc.insecure_channel(self._target)
            self._stub = realestate_pb2_grpc.DomainStub(self._channel)
        return self._stub

    def push(self, packet: HandoffPacket) -> str:
        """Map ``packet`` to the proto and call ``EnqueueHandoff``; return its id.

        The proto ``HandoffPacket`` carries lead_id, trigger, confidence, reason,
        transcript, and recommended_action. The richer local fields
        (completed_steps, retrieved_evidence) are folded into ``reason`` so no
        context is lost until the proto gains those fields.
        """
        from genproto.realestate.v1 import realestate_pb2

        stub = self._ensure_stub()
        proto = realestate_pb2.HandoffPacket(
            lead_id=packet.lead_id,
            trigger=packet.trigger.value,
            confidence=packet.confidence,
            reason=self._enrich_reason(packet),
            transcript=packet.transcript,
            recommended_action=packet.recommended_action,
        )
        response = stub.EnqueueHandoff(proto)
        return response.handoff_id

    @staticmethod
    def _enrich_reason(packet: HandoffPacket) -> str:
        """Fold steps + evidence into the reason so context survives the proto."""
        parts = [packet.reason]
        if packet.completed_steps:
            parts.append(f"completed_steps={packet.completed_steps}")
        if packet.retrieved_evidence:
            parts.append(f"retrieved_evidence={packet.retrieved_evidence}")
        return " | ".join(parts)


# --------------------------------------------------------------------------- #
# The decision entry point.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HandoffDecision:
    """The outcome of :func:`decide` (loggable).

    ``decision`` is proceed | escalate. ``score`` is the composite confidence.
    ``packet`` is the enqueued :class:`HandoffPacket` (present iff escalated).
    ``handoff_id`` is the sink's id (present iff escalated). ``reason`` explains
    the routing.
    """

    decision: Decision
    score: ConfidenceScore
    reason: str
    packet: Optional[HandoffPacket] = None
    handoff_id: Optional[str] = None

    @property
    def escalated(self) -> bool:
        """True iff the message was routed to a human."""
        return self.decision is Decision.ESCALATE


def _first_trigger(
    *,
    text: str,
    amount: Optional[float],
    fair_housing: Optional[FairHousingResult],
    high_dollar_band: float,
) -> Optional[Trigger]:
    """Return the first firing HARD trigger, in priority order, or ``None``.

    Hard triggers are checked regardless of the confidence score. Order is a
    stable reporting choice; any one firing forces escalation.
    """
    if fair_housing is not None and fair_housing.escalate:
        return Trigger.FAIR_HOUSING
    if detect_legal_upl(text):
        return Trigger.LEGAL_UPL
    if detect_human_request(text):
        return Trigger.HUMAN_REQUEST
    if detect_hostile_sentiment(text):
        return Trigger.HOSTILE_SENTIMENT
    if amount is not None and amount >= high_dollar_band:
        return Trigger.HIGH_DOLLAR
    return None


def _trigger_reason(
    trigger: Trigger,
    *,
    amount: Optional[float],
    fair_housing: Optional[FairHousingResult],
    high_dollar_band: float,
) -> str:
    """A human-readable audit line for a firing trigger."""
    if trigger is Trigger.FAIR_HOUSING:
        fh = fair_housing.reason if fair_housing else "fair housing rail tripped"
        return f"HARD TRIGGER fair_housing: {fh}"
    if trigger is Trigger.LEGAL_UPL:
        return (
            "HARD TRIGGER legal_complexity/UPL: request for custom contract "
            "clause or legal advice — the agent does not practice law"
        )
    if trigger is Trigger.HUMAN_REQUEST:
        return "HARD TRIGGER explicit_human_request: consumer asked for a person"
    if trigger is Trigger.HOSTILE_SENTIMENT:
        return (
            "HARD TRIGGER hostile/distressed/FH-sensitive sentiment detected"
        )
    if trigger is Trigger.HIGH_DOLLAR:
        return (
            f"HARD TRIGGER high_dollar_value: amount {amount} >= band "
            f"{high_dollar_band} (binding commitment / high financial stakes)"
        )
    return "low composite confidence below ops threshold"


def decide(
    *,
    lead_id: str,
    result: VerificationResult,
    fair_housing: Optional[FairHousingResult],
    text: str,
    sink: HandoffSink,
    transcript: str = "",
    amount: Optional[float] = None,
    completed_steps: Optional[List[str]] = None,
    recommended_action: str = "",
    self_consistency: Optional[float] = None,
    high_stakes: bool = False,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    high_dollar_band: float = DEFAULT_HIGH_DOLLAR_BAND,
) -> HandoffDecision:
    """Route a message: proceed, or escalate (enqueuing a handoff packet).

    Inputs: a U6 :class:`VerificationResult`, an optional U7
    :class:`FairHousingResult`, the consumer ``text``, and conversation context
    (``transcript``, ``amount``, ``completed_steps``). The composite confidence
    (:func:`composite_confidence`) is computed from ``result`` (+ optional
    ``self_consistency`` for ``high_stakes`` claims).

    Decision order:

    1. **Hard triggers** (legal/UPL, high dollar, hostile sentiment, Fair
       Housing trip, explicit human request) FORCE escalation regardless of the
       composite score — checked first so a *confidently* wrong/out-of-scope
       move still escalates.
    2. Otherwise, a composite **below ``confidence_threshold``** escalates as the
       soft trigger.
    3. Otherwise, **proceed**.

    On escalation a :class:`HandoffPacket` is built (with full resumable context
    and the Critic's cited evidence) and pushed to ``sink``.
    """
    score = composite_confidence(
        result, self_consistency=self_consistency, high_stakes=high_stakes
    )
    steps = list(completed_steps or [])
    evidence = list(result.citations)

    hard = _first_trigger(
        text=text,
        amount=amount,
        fair_housing=fair_housing,
        high_dollar_band=high_dollar_band,
    )

    if hard is not None:
        reason = _trigger_reason(
            hard,
            amount=amount,
            fair_housing=fair_housing,
            high_dollar_band=high_dollar_band,
        )
        return _escalate(
            lead_id=lead_id,
            trigger=hard,
            score=score,
            reason=reason,
            transcript=transcript,
            steps=steps,
            evidence=evidence,
            recommended_action=recommended_action,
            sink=sink,
        )

    if score.score < confidence_threshold:
        reason = (
            f"SOFT TRIGGER low_confidence: composite {score.score:.2f} below "
            f"ops threshold {confidence_threshold:.2f} — {score.reason}"
        )
        return _escalate(
            lead_id=lead_id,
            trigger=Trigger.LOW_CONFIDENCE,
            score=score,
            reason=reason,
            transcript=transcript,
            steps=steps,
            evidence=evidence,
            recommended_action=recommended_action,
            sink=sink,
        )

    return HandoffDecision(
        decision=Decision.PROCEED,
        score=score,
        reason=(
            f"proceed: no hard trigger and composite {score.score:.2f} >= "
            f"threshold {confidence_threshold:.2f}"
        ),
    )


def _escalate(
    *,
    lead_id: str,
    trigger: Trigger,
    score: ConfidenceScore,
    reason: str,
    transcript: str,
    steps: List[str],
    evidence: List[str],
    recommended_action: str,
    sink: HandoffSink,
) -> HandoffDecision:
    """Build the packet, push it to the sink, and return the escalate decision."""
    action = recommended_action or _default_action(trigger)
    packet = HandoffPacket(
        lead_id=lead_id,
        trigger=trigger,
        confidence=score.score,
        reason=reason,
        transcript=transcript,
        completed_steps=steps,
        retrieved_evidence=evidence,
        recommended_action=action,
        hard_trigger=trigger.is_hard,
    )
    handoff_id = sink.push(packet)
    return HandoffDecision(
        decision=Decision.ESCALATE,
        score=score,
        reason=reason,
        packet=packet,
        handoff_id=handoff_id,
    )


def _default_action(trigger: Trigger) -> str:
    """A sensible recommended action when the caller supplies none."""
    return {
        Trigger.LEGAL_UPL: "Licensed broker/attorney to advise; do not draft clause language.",
        Trigger.HIGH_DOLLAR: "Licensed broker to review the high-value commitment before any reply.",
        Trigger.HOSTILE_SENTIMENT: "Human agent to de-escalate and take over the conversation.",
        Trigger.FAIR_HOUSING: "Compliance/broker review of the Fair Housing trip before any reply.",
        Trigger.HUMAN_REQUEST: "Connect the consumer to a live human agent.",
        Trigger.LOW_CONFIDENCE: "Human to verify the draft against source data before sending.",
    }[trigger]
