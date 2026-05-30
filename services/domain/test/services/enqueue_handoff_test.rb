require "test_helper"

class EnqueueHandoffTest < ActiveSupport::TestCase
  setup do
    @lead = Lead.create!(side: "seller", address: "21 Guadalupe", intent: "high")
  end

  test "enqueues a pending handoff packet on the broker queue" do
    packet = EnqueueHandoff.call(lead: @lead, trigger: "legal_complexity", confidence: 0.2,
                                 reason: "custom clause", recommended_action: "broker review")
    assert packet.persisted?
    assert_equal "pending", packet.status
    assert_includes HandoffPacket.queue, packet
  end

  test "writes an audit trail row for the escalation" do
    assert_difference -> { AuditEvent.where(kind: "confidence_handoff").count }, 1 do
      EnqueueHandoff.call(lead: @lead, trigger: "hostile", confidence: 0.1)
    end
  end
end
