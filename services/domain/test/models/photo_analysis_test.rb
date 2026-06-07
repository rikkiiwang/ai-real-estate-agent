require "test_helper"

class PhotoAnalysisTest < ActiveSupport::TestCase
  def prop
    @prop ||= Property.create!(address: "1 Oak St", state: "listed", list_price: 500_000)
  end

  test "requires an address and is unique case-insensitively" do
    PhotoAnalysis.create!(address: "1 Oak St", property: prop)
    dup = PhotoAnalysis.new(address: "1 OAK ST")
    refute dup.valid?
  end

  test "fresh? reflects the TTL" do
    pa = PhotoAnalysis.new(analyzed_at: Time.current)
    assert pa.fresh?
    pa.analyzed_at = 31.days.ago
    refute pa.fresh?
  end

  test "feature_findings and review_findings expose the JSON arrays" do
    pa = PhotoAnalysis.create!(address: "1 Oak St", property: prop,
      findings: [{ "kind" => "feature", "label" => "updated_kitchen", "confidence" => 0.9 }],
      needs_review: [{ "kind" => "red_flag", "label" => "water_stain", "confidence" => 0.7 }])
    assert_equal "updated_kitchen", pa.feature_findings.first["label"]
    assert_equal "water_stain", pa.review_findings.first["label"]
  end

  test "from_claude? distinguishes real analysis from sample" do
    assert PhotoAnalysis.new(provenance: "claude").from_claude?
    refute PhotoAnalysis.new(provenance: "sample").from_claude?
  end
end
