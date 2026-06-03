require "test_helper"
require "realestate/v1/realestate_services_pb"

class BrainConversationClientTest < ActiveSupport::TestCase
  # A fake gRPC stub that returns a canned OrchestrateResponse (or raises).
  class FakeStub
    def initialize(resp: nil, error: nil)
      @resp = resp
      @error = error
    end

    def orchestrate(_request)
      raise @error if @error

      @resp
    end
  end

  def grounded_response
    Realestate::V1::OrchestrateResponse.new(
      outcome: "send", escalated: false, final_message: "It looks fairly priced.",
      confidence: 0.82, coverage: 0.9, agreement: 0.8, self_consistency: 0.75,
      fair_housing_allowed: true,
      claims: [
        Realestate::V1::ReasoningClaim.new(claim: "Comparable sales cluster near $610k",
          label: "entailed", score: 0.91, source_kind: "comparable_sale", supported: true)
      ],
      steps: [Realestate::V1::ReasoningStep.new(node: "decide", title: "Decide", detail: "send", status: "ok")]
    )
  end

  test "maps a grounded response into value objects with claims and steps" do
    client = BrainConversationClient.new(stub: FakeStub.new(resp: grounded_response))
    result = client.orchestrate(query: "is this priced well?", address: "1 Mueller")

    assert result.ok?
    assert_equal "send", result.outcome
    assert_equal "It looks fairly priced.", result.message
    assert_in_delta 0.82, result.confidence, 0.001
    assert_equal 1, result.claims.size
    assert_equal "comparable_sale", result.claims.first.source_kind
    assert result.claims.first.supported
    assert_equal "decide", result.steps.first.node
    assert_nil result.handoff
  end

  test "maps an escalated response into a handoff" do
    resp = Realestate::V1::OrchestrateResponse.new(
      outcome: "handoff", escalated: true, final_message: "Let me bring in a broker.",
      handoff_trigger: "legal_complexity_upl", handoff_reason: "legal question", hard_trigger: true
    )
    client = BrainConversationClient.new(stub: FakeStub.new(resp: resp))
    result = client.orchestrate(query: "can you add a clause?")

    assert result.handoff?
    assert result.handoff.hard
    assert_equal "legal_complexity_upl", result.handoff.trigger
  end

  test "a brain failure degrades gracefully instead of raising" do
    client = BrainConversationClient.new(stub: FakeStub.new(error: StandardError.new("boom")))
    result = client.orchestrate(query: "hi")

    assert_not result.ok?
    assert_equal "agent_unavailable", result.error
    assert_match(/taking a moment/i, result.message)
    assert_empty result.claims
  end
end
