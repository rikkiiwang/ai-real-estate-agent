require "test_helper"
require "realestate/v1/realestate_services_pb"

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

  test "sends features + comps and maps freshness fields back" do
    captured = nil
    fake_stub = Object.new
    fake_stub.define_singleton_method(:get_valuation) do |req|
      captured = req
      Realestate::V1::GetValuationResponse.new(
        sufficient_data: true, estimate: 480_000, low: 440_000, high: 520_000,
        as_of: "2026-06-05T00:00:00Z", recent_activity: "3 new in 30d",
        facts: [Realestate::V1::SourceFact.new(source_id: "comp:1", kind: "comp:active_listing",
                                               description: "Active listing 2 Oak", contribution: 0)]
      )
    end

    comp = CompsSelector::Comp.new(id: "1", address: "2 Oak", price: 500_000, sqft: 2000,
                                   beds: 4, baths: 2, distance_mi: 0.3, age_days: 5)
    result = BrainValuationClient.new(stub: fake_stub).valuation(
      address: "1 Oak St",
      features: { beds: 4, baths: 2.5, sqft: 2000, year_built: 1998, latitude: 30.24, longitude: -97.77 },
      comps: [comp],
      as_of: "2026-06-05T00:00:00Z",
      recent_activity: "3 new in 30d",
    )

    assert_equal 4, captured.features.beds
    assert_equal 1, captured.comps.size
    assert_equal 500_000, captured.comps.first.price
    assert result.usable?
    assert_equal "2026-06-05T00:00:00Z", result.as_of
    assert_equal "3 new in 30d", result.recent_activity
  end

  test "address-only call still works (no features)" do
    fake_stub = Object.new
    fake_stub.define_singleton_method(:get_valuation) do |req|
      Realestate::V1::GetValuationResponse.new(sufficient_data: true, estimate: 500_000)
    end
    result = BrainValuationClient.new(stub: fake_stub).valuation(address: "5 Elm")
    assert result.usable?
    assert_nil result.as_of
  end
end
