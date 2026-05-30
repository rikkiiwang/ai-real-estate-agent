require "test_helper"

class HandoffPacketTest < ActiveSupport::TestCase
  setup do
    @lead = Lead.create!(side: "seller", address: "13 Pine", intent: "high")
  end

  test "valid packet persists" do
    packet = @lead.handoff_packets.create!(trigger: "low_confidence", confidence: 0.4, reason: "sparse data")
    assert packet.persisted?
    assert_equal "pending", packet.status
  end

  test "requires a trigger" do
    assert_not HandoffPacket.new(lead: @lead).valid?
  end

  test "confidence must be in 0..1" do
    assert_not HandoffPacket.new(lead: @lead, trigger: "x", confidence: 1.5).valid?
  end

  test "queue scope returns only pending, newest first" do
    old = @lead.handoff_packets.create!(trigger: "a", created_at: 2.hours.ago)
    new = @lead.handoff_packets.create!(trigger: "b")
    @lead.handoff_packets.create!(trigger: "c", status: "resolved")
    assert_equal [ new, old ], HandoffPacket.queue.to_a
  end
end
