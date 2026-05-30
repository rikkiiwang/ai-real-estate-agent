"""U8 tests — composite confidence + HITL handoff (deterministic, stdlib only).

Covers AE3 / R13. The decision layer routes a verified message to a human on
hard triggers or low confidence, and proceeds otherwise:

* high-confidence grounded result PROCEEDS (no handoff);
* a request for a custom contract clause FORCES handoff (legal/UPL) EVEN at high
  confidence;
* hostile sentiment FORCES handoff;
* a composite just below threshold ESCALATES with a reason;
* a Fair Housing rail trip FORCES handoff;
* an explicit "I want a human" FORCES handoff;
* the handoff packet carries FULL resumable context and lands in the sink;
* ``DomainGrpcHandoffSink`` constructs WITHOUT connecting (import-safe, lazy).

No network. The gRPC sink is exercised only for import-safety / lazy-connect.
"""
from __future__ import annotations

from brain.lawyer.confidence import (
    CALIBRATION_FOLLOWUP,
    ConfidenceScore,
    composite_confidence,
)
from brain.lawyer.critic import ClaimVerdict, VerificationResult
from brain.lawyer.entailment import Label
from brain.lawyer.fair_housing import scan_output
from brain.lawyer.handoff import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    Decision,
    DomainGrpcHandoffSink,
    FakeHandoffSink,
    HandoffPacket,
    Trigger,
    decide,
    detect_hostile_sentiment,
    detect_human_request,
    detect_legal_upl,
)


# --------------------------------------------------------------------------- #
# Helpers — build VerificationResults directly so the decision layer is tested
# in isolation from the Critic's retrieval/entailment plumbing.
# --------------------------------------------------------------------------- #
def _entailed_verdict(i: int, claim: str, *, score: float = 0.95) -> ClaimVerdict:
    return ClaimVerdict(
        index=i,
        claim=claim,
        label=Label.ENTAILED,
        score=score,
        citation=f"src-{i}",
        source_kind="tcad",
        reason="entailed by source",
    )


def _baseless_verdict(i: int, claim: str) -> ClaimVerdict:
    return ClaimVerdict(
        index=i,
        claim=claim,
        label=Label.BASELESS,
        score=0.0,
        citation=None,
        source_kind=None,
        reason="no source",
    )


def _grounded_result() -> VerificationResult:
    """A fully-grounded, high-confidence verification result."""
    verdicts = [
        _entailed_verdict(0, "The home has 3 bedrooms"),
        _entailed_verdict(1, "It is listed at $525,000"),
    ]
    return VerificationResult(
        approved=True,
        escalate=False,
        confidence=0.95,
        reason="all claims entailed by source data and cited",
        claims=verdicts,
        approved_message="The home has 3 bedrooms. It is listed at $525,000.",
    )


def _weak_result() -> VerificationResult:
    """A partly-ungrounded result that should drag the composite down."""
    verdicts = [
        _entailed_verdict(0, "It is listed at $525,000", score=0.7),
        _baseless_verdict(1, "It was recently renovated"),
    ]
    return VerificationResult(
        approved=False,
        escalate=True,
        confidence=0.35,
        reason="1 unsupported claim",
        claims=verdicts,
        approved_message="It is listed at $525,000.",
    )


# --------------------------------------------------------------------------- #
# Composite confidence unit behaviour.
# --------------------------------------------------------------------------- #
def test_composite_high_for_grounded_result():
    score = composite_confidence(_grounded_result())
    assert isinstance(score, ConfidenceScore)
    assert score.score >= DEFAULT_CONFIDENCE_THRESHOLD
    assert score.uncalibrated is True
    assert 0.0 <= score.signals.retrieval_coverage <= 1.0


def test_composite_low_for_weak_result():
    score = composite_confidence(_weak_result())
    assert score.score < DEFAULT_CONFIDENCE_THRESHOLD
    # Coverage is the weak signal here (half the claims are baseless).
    assert score.signals.retrieval_coverage == 0.5


def test_high_stakes_without_self_consistency_is_conservative():
    grounded = _grounded_result()
    base = composite_confidence(grounded).score
    flagged = composite_confidence(grounded, high_stakes=True).score
    # Flagging high-stakes with no self-consistency measurement pulls it down.
    assert flagged < base


def test_calibration_followup_is_flagged():
    assert "UNCALIBRATED" in CALIBRATION_FOLLOWUP
    assert "calibrate" in CALIBRATION_FOLLOWUP.lower()


# --------------------------------------------------------------------------- #
# Detectors.
# --------------------------------------------------------------------------- #
def test_detectors():
    assert detect_legal_upl("Can you add a custom clause for the inspection?")
    assert detect_legal_upl("Please draft a special provision about the fence.")
    assert not detect_legal_upl("What is the listing price?")
    assert detect_hostile_sentiment("This is a total scam, I'm going to sue you!")
    assert not detect_hostile_sentiment("Thanks, that is helpful.")
    assert detect_human_request("I want to speak to a real human agent.")
    assert not detect_human_request("What are the property taxes?")


# --------------------------------------------------------------------------- #
# AE3 happy path: high-confidence grounded result proceeds, no handoff.
# --------------------------------------------------------------------------- #
def test_grounded_high_confidence_proceeds():
    sink = FakeHandoffSink()
    decision = decide(
        lead_id="lead-1",
        result=_grounded_result(),
        fair_housing=scan_output("The home has 3 bedrooms and is listed at $525,000."),
        text="What does the home have and what is the price?",
        sink=sink,
        transcript="...",
        amount=None,
    )
    assert decision.decision is Decision.PROCEED
    assert decision.escalated is False
    assert decision.packet is None
    assert sink.packets == []


# --------------------------------------------------------------------------- #
# AE3 critical: custom contract clause forces handoff EVEN at high confidence.
# --------------------------------------------------------------------------- #
def test_custom_clause_forces_handoff_even_at_high_confidence():
    sink = FakeHandoffSink()
    decision = decide(
        lead_id="lead-2",
        result=_grounded_result(),  # high confidence
        fair_housing=scan_output("Sure."),
        text="Can you add a custom clause waiving the inspection contingency?",
        sink=sink,
        transcript="buyer: add custom clause ...",
    )
    assert decision.escalated is True
    assert decision.packet is not None
    assert decision.packet.trigger is Trigger.LEGAL_UPL
    assert decision.packet.hard_trigger is True
    # Fired despite a high composite score.
    assert decision.score.score >= DEFAULT_CONFIDENCE_THRESHOLD
    assert len(sink.packets) == 1


# --------------------------------------------------------------------------- #
# AE3 critical: hostile sentiment forces handoff.
# --------------------------------------------------------------------------- #
def test_hostile_sentiment_forces_handoff():
    sink = FakeHandoffSink()
    decision = decide(
        lead_id="lead-3",
        result=_grounded_result(),
        fair_housing=scan_output("I understand your concern."),
        text="This whole thing is a scam and I am going to sue you!",
        sink=sink,
    )
    assert decision.escalated is True
    assert decision.packet.trigger is Trigger.HOSTILE_SENTIMENT
    assert decision.packet.hard_trigger is True
    assert len(sink.packets) == 1


# --------------------------------------------------------------------------- #
# AE3 edge: score just below threshold escalates with a reason.
# --------------------------------------------------------------------------- #
def test_score_just_below_threshold_escalates_with_reason():
    sink = FakeHandoffSink()
    decision = decide(
        lead_id="lead-4",
        result=_weak_result(),  # composite below threshold, no hard trigger
        fair_housing=scan_output("It is listed at $525,000."),
        text="Tell me about the home.",
        sink=sink,
    )
    assert decision.escalated is True
    assert decision.packet.trigger is Trigger.LOW_CONFIDENCE
    assert decision.packet.hard_trigger is False
    assert "low_confidence" in decision.reason
    assert decision.score.score < DEFAULT_CONFIDENCE_THRESHOLD
    assert len(sink.packets) == 1


# --------------------------------------------------------------------------- #
# AE3 critical: a Fair Housing rail trip forces handoff.
# --------------------------------------------------------------------------- #
def test_fair_housing_trip_forces_handoff():
    sink = FakeHandoffSink()
    # A draft naming a steering proxy trips the rail (allowed=False, escalate).
    fh = scan_output("This is a safe, family-friendly neighborhood.")
    assert fh.escalate is True
    decision = decide(
        lead_id="lead-5",
        result=_grounded_result(),  # high confidence
        fair_housing=fh,
        text="Is this a good neighborhood?",
        sink=sink,
    )
    assert decision.escalated is True
    assert decision.packet.trigger is Trigger.FAIR_HOUSING
    assert decision.packet.hard_trigger is True
    assert len(sink.packets) == 1


# --------------------------------------------------------------------------- #
# Explicit "I want a human" forces handoff.
# --------------------------------------------------------------------------- #
def test_explicit_human_request_forces_handoff():
    sink = FakeHandoffSink()
    decision = decide(
        lead_id="lead-6",
        result=_grounded_result(),
        fair_housing=scan_output("Of course."),
        text="Please connect me to a real human agent.",
        sink=sink,
    )
    assert decision.escalated is True
    assert decision.packet.trigger is Trigger.HUMAN_REQUEST
    assert len(sink.packets) == 1


# --------------------------------------------------------------------------- #
# High dollar value above the band forces handoff.
# --------------------------------------------------------------------------- #
def test_high_dollar_value_forces_handoff():
    sink = FakeHandoffSink()
    decision = decide(
        lead_id="lead-7",
        result=_grounded_result(),
        fair_housing=scan_output("Understood."),
        text="I accept the offer.",
        sink=sink,
        amount=750_000.0,
        high_dollar_band=100_000.0,
    )
    assert decision.escalated is True
    assert decision.packet.trigger is Trigger.HIGH_DOLLAR
    assert decision.packet.hard_trigger is True


# --------------------------------------------------------------------------- #
# Integration: the handoff packet carries full resumable context into the sink.
# --------------------------------------------------------------------------- #
def test_packet_carries_full_context_into_sink():
    sink = FakeHandoffSink()
    decision = decide(
        lead_id="lead-8",
        result=_grounded_result(),
        fair_housing=scan_output("Sure."),
        text="Can you write a special provision into the contract?",
        sink=sink,
        transcript="buyer: hi\nagent: hi\nbuyer: write a special provision",
        completed_steps=["qualified buyer", "pulled comps", "drafted summary"],
        recommended_action="Broker to advise on contract language.",
    )
    assert len(sink.packets) == 1
    packet: HandoffPacket = sink.packets[0]
    assert packet.lead_id == "lead-8"
    assert packet.trigger is Trigger.LEGAL_UPL
    assert packet.transcript.startswith("buyer: hi")
    assert packet.completed_steps == ["qualified buyer", "pulled comps", "drafted summary"]
    # Critic-cited evidence is carried through.
    assert packet.retrieved_evidence == ["src-0", "src-1"]
    assert packet.recommended_action == "Broker to advise on contract language."
    assert 0.0 <= packet.confidence <= 1.0
    # And it is loggable as a plain dict.
    d = packet.to_dict()
    assert d["trigger"] == Trigger.LEGAL_UPL.value
    assert d["completed_steps"] == packet.completed_steps


def test_default_recommended_action_is_supplied_when_omitted():
    sink = FakeHandoffSink()
    decision = decide(
        lead_id="lead-9",
        result=_grounded_result(),
        fair_housing=scan_output("Sure."),
        text="connect me to a human please",
        sink=sink,
    )
    assert decision.packet.recommended_action  # non-empty default


# --------------------------------------------------------------------------- #
# Hard triggers take precedence over the (passing) confidence check.
# --------------------------------------------------------------------------- #
def test_hard_trigger_beats_high_confidence_threshold_config():
    sink = FakeHandoffSink()
    # Even with the threshold set to 0 (so confidence never escalates), a hard
    # trigger still fires.
    decision = decide(
        lead_id="lead-10",
        result=_grounded_result(),
        fair_housing=scan_output("ok"),
        text="add a custom clause to the offer",
        sink=sink,
        confidence_threshold=0.0,
    )
    assert decision.escalated is True
    assert decision.packet.trigger is Trigger.LEGAL_UPL


# --------------------------------------------------------------------------- #
# DomainGrpcHandoffSink: import-safe and constructs WITHOUT connecting.
# --------------------------------------------------------------------------- #
def test_domain_grpc_sink_constructs_without_connecting():
    sink = DomainGrpcHandoffSink(target="localhost:50051")
    # No channel/stub created at construction (lazy connect).
    assert sink._channel is None
    assert sink._stub is None


def test_domain_grpc_sink_maps_packet_to_proto_without_network():
    # Exercise the proto mapping by stubbing the channel/stub so no socket opens.
    sink = DomainGrpcHandoffSink(target="localhost:50051")

    captured = {}

    class _StubSpy:
        def EnqueueHandoff(self, proto):
            captured["proto"] = proto

            class _Resp:
                handoff_id = "h-123"

            return _Resp()

    # Inject a fake stub so _ensure_stub() short-circuits (still no network).
    sink._stub = _StubSpy()

    packet = HandoffPacket(
        lead_id="lead-11",
        trigger=Trigger.LEGAL_UPL,
        confidence=0.91,
        reason="UPL",
        transcript="t",
        completed_steps=["a"],
        retrieved_evidence=["src-0"],
        recommended_action="broker",
        hard_trigger=True,
    )
    handoff_id = sink.push(packet)
    assert handoff_id == "h-123"
    proto = captured["proto"]
    assert proto.lead_id == "lead-11"
    assert proto.trigger == Trigger.LEGAL_UPL.value
    assert abs(proto.confidence - 0.91) < 1e-6
    assert proto.recommended_action == "broker"
    # Steps + evidence folded into the proto reason so no context is lost.
    assert "completed_steps" in proto.reason
    assert "retrieved_evidence" in proto.reason
