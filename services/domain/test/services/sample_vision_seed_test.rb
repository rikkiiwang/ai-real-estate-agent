require "test_helper"

class SampleVisionSeedTest < ActiveSupport::TestCase
  def listing(addr, photos: ["https://example.test/a.jpg"])
    Property.create!(address: addr, state: "listed", region: "Zilker", list_price: 600_000,
                     sqft: 2000, beds: 3, baths: 2, photo_urls: photos, source_name: "Sample",
                     captured_at: Time.current)
  end

  test "seeds labeled sample photo analysis per listing" do
    p1 = listing("1 A St, Austin, TX 78704")
    listing("2 B St, Austin, TX 78704")

    assert_difference -> { PhotoAnalysis.count }, 2 do
      SampleVisionSeed.call
    end

    pa = PhotoAnalysis.find_by(address: p1.address)
    assert_equal "sample", pa.provenance
    refute pa.from_claude?
    assert pa.feature_findings.any?
    assert pa.feature_findings.all? { |f| f["kind"] == "feature" }     # only buyer-safe features
    assert pa.review_findings.empty?                                    # no red-flags in sample
    assert_operator pa.condition.to_f, :>, 0.5                          # features raise condition
    assert_operator pa.condition.to_f, :<=, 1.0
    # each finding is cited to the listing's photo
    assert_equal "https://example.test/a.jpg", pa.feature_findings.first["evidence_photo_id"]
  end

  test "is idempotent" do
    listing("1 A St, Austin, TX 78704")
    SampleVisionSeed.call
    assert_no_difference -> { PhotoAnalysis.count } do
      SampleVisionSeed.call
    end
  end
end
