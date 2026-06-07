require "test_helper"

class VisionAnalyzeRunTest < ActiveSupport::TestCase
  # A fake vision client recording calls and returning a canned result.
  class FakeClient
    attr_reader :calls

    def initialize(condition: 0.8)
      @calls = []
      @condition = condition
    end

    def analyze(address:, photo_urls:)
      @calls << address
      BrainVisionClient::Result.new(
        findings: [BrainVisionClient::Finding.new(kind: "feature", label: "updated_kitchen", confidence: 0.9, evidence_photo_id: "x")],
        condition: @condition,
        needs_review: [BrainVisionClient::Finding.new(kind: "red_flag", label: "water_stain", confidence: 0.7, evidence_photo_id: "x")],
        provenance: "claude", error: nil
      )
    end
  end

  def listing(addr)
    Property.create!(address: addr, state: "listed", region: "Zilker", list_price: 500_000,
                     sqft: 2000, photo_urls: ["https://example.test/a.jpg"], source_name: "S", captured_at: Time.current)
  end

  test "analyzes listings and caches the result (condition + findings + provenance)" do
    p1 = listing("1 A St")
    client = FakeClient.new(condition: 0.82)

    result = VisionAnalyzeRun.new(client: client).call(properties: [p1], max_calls: 25)

    assert_equal 1, result.analyzed
    pa = PhotoAnalysis.find_by(address: "1 A St")
    assert_in_delta 0.82, pa.condition.to_f, 0.001
    assert_equal "claude", pa.provenance
    assert_equal "updated_kitchen", pa.feature_findings.first["label"]
    assert_equal "water_stain", pa.review_findings.first["label"]   # red-flag cached for the broker
  end

  test "skips fresh rows without a call (cache-first)" do
    p1 = listing("1 A St")
    PhotoAnalysis.create!(address: "1 A St", property: p1, analyzed_at: Time.current,
                          condition: 0.5, provenance: "claude")
    client = FakeClient.new

    result = VisionAnalyzeRun.new(client: client).call(properties: [p1], max_calls: 25)

    assert_equal 0, result.analyzed
    assert_equal 1, result.skipped_fresh
    assert_empty client.calls
  end

  test "respects the MAX_CALLS budget" do
    props = 3.times.map { |i| listing("#{i} A St") }
    client = FakeClient.new

    result = VisionAnalyzeRun.new(client: client).call(properties: props, max_calls: 2)

    assert_equal 2, result.analyzed
    assert_equal 1, result.skipped_budget
    assert_equal 2, client.calls.size
  end

  test "a stale row is re-analyzed (upsert)" do
    p1 = listing("1 A St")
    PhotoAnalysis.create!(address: "1 A St", property: p1, analyzed_at: 40.days.ago,
                          condition: 0.3, provenance: "claude")
    client = FakeClient.new(condition: 0.9)

    assert_no_difference -> { PhotoAnalysis.count } do
      VisionAnalyzeRun.new(client: client).call(properties: [p1], max_calls: 25)
    end
    assert_in_delta 0.9, PhotoAnalysis.find_by(address: "1 A St").condition.to_f, 0.001
  end
end
