require "test_helper"

# Exercises the gRPC handler methods directly (no socket): proves the protobuf
# request/response mapping is bound to the domain service objects.
class DomainServerTest < ActiveSupport::TestCase
  setup { @server = DomainServer.new }

  test "CreateLead handler creates a Lead and returns the proto message" do
    request = Realestate::V1::CreateLeadRequest.new(side: "seller", address: "30 Congress Ave", contact: "s@x.com")
    response = @server.create_lead(request)

    assert_kind_of Realestate::V1::Lead, response
    assert_equal "seller", response.side
    assert_equal "30 Congress Ave", response.address
    assert Lead.exists?(response.id.to_i)
  end

  test "EnqueueHandoff handler enqueues a packet and returns its id" do
    lead = Lead.create!(side: "buyer", address: "31 Lavaca", intent: "high")
    request = Realestate::V1::HandoffPacket.new(
      lead_id: lead.id.to_s, trigger: "low_confidence", confidence: 0.3,
      reason: "sparse", transcript: "...", recommended_action: "review"
    )
    response = @server.enqueue_handoff(request)

    assert_kind_of Realestate::V1::EnqueueHandoffResponse, response
    packet = HandoffPacket.find(response.handoff_id.to_i)
    assert_equal "low_confidence", packet.trigger
    assert_includes HandoffPacket.queue, packet
  end
end
