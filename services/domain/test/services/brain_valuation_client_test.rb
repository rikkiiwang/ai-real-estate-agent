require "test_helper"

class BrainValuationClientTest < ActiveSupport::TestCase
  class FakeStub
    def initialize(resp: nil, error: nil)
      @resp = resp
      @error = error
    end

    def get_valuation(_request)
      raise @error if @error

      @resp
    end
  end

  test "maps a sufficient valuation with cited facts" do
    resp = Realestate::V1::GetValuationResponse.new(
      sufficient_data: true, estimate: 615_000, low: 590_000, high: 640_000,
      facts: [Realestate::V1::SourceFact.new(source_id: "tcad-1", kind: "tcad_appraisal", description: "TCAD appraised value $602k")]
    )
    result = BrainValuationClient.new(stub: FakeStub.new(resp: resp)).valuation(address: "1 Main")
    assert result.usable?
    assert_equal 615_000, result.estimate
    assert_equal 1, result.facts.size
    assert_equal "tcad_appraisal", result.facts.first.kind
  end

  test "insufficient data is not usable" do
    resp = Realestate::V1::GetValuationResponse.new(sufficient_data: false, estimate: 0)
    result = BrainValuationClient.new(stub: FakeStub.new(resp: resp)).valuation(address: "1 Main")
    assert result.ok?
    assert_not result.usable?
  end

  test "a brain failure degrades gracefully" do
    result = BrainValuationClient.new(stub: FakeStub.new(error: StandardError.new("boom"))).valuation(address: "1 Main")
    assert_not result.ok?
    assert_equal "valuation_unavailable", result.error
  end
end
