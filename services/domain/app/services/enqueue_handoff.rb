# Domain operation backing the gRPC Domain.EnqueueHandoff RPC.
#
# Enqueues a HandoffPacket onto the broker handoff queue and logs the rail
# trip to the append-only audit log. Wired to DomainServer; also unit-tested
# directly.
class EnqueueHandoff
  def self.call(lead:, trigger:, confidence: nil, reason: nil, transcript: nil, recommended_action: nil)
    packet = HandoffPacket.create!(
      lead: lead,
      trigger: trigger,
      confidence: confidence,
      reason: reason,
      transcript: transcript,
      recommended_action: recommended_action,
      status: "pending"
    )

    AuditEvent.record_rail_trip(
      kind: "confidence_handoff",
      decision: "escalated",
      subject: packet,
      detail: "trigger=#{trigger} confidence=#{confidence} reason=#{reason}"
    )

    packet
  end
end
