require "test_helper"

class SampleCrossSourceSeedTest < ActiveSupport::TestCase
  def listing(addr, price:, sqft: 2000, region: "Zilker")
    Property.create!(address: addr, state: "listed", region: region, list_price: price,
                     sqft: sqft, beds: 3, baths: 2, source_name: "Sample", captured_at: Time.current)
  end

  test "seeds labeled sample market snapshots and tax records" do
    p1 = listing("1 A St, Austin, TX 78704", price: 600_000)
    listing("2 B St, Austin, TX 78704", price: 800_000)

    assert_difference("MarketSnapshot.count" => 1, "PropertyRecordCache.count" => 2) do
      SampleCrossSourceSeed.call
    end

    snap = MarketSnapshot.find_by(area: "Zilker")
    assert_equal "Curated Austin sample", snap.source
    assert snap.avg_price_per_sqft.to_f.positive?
    assert_equal "78704", snap.zip # ZIP lifted from a listing address

    rec = PropertyRecordCache.find_by(address: p1.address)
    assert rec.tax_assessed_value.to_i.positive?
    assert_operator rec.tax_assessed_value.to_i, :<, p1.list_price # assessed below asking
  end

  test "is idempotent — re-running does not duplicate" do
    listing("1 A St, Austin, TX 78704", price: 600_000)
    SampleCrossSourceSeed.call

    assert_no_difference ["MarketSnapshot.count", "PropertyRecordCache.count"] do
      SampleCrossSourceSeed.call
    end
  end

  test "a seeded listing reconciles to asking + tax + market" do
    p1 = listing("1 A St, Austin, TX 78704", price: 600_000)
    SampleCrossSourceSeed.call

    r = CrossSourceReconciliation.for(property: p1.reload)
    assert_operator r.sources.size, :>=, 3 # asking + tax + market (no valuation here)
    assert_includes r.sources.map(&:source_id), "tax:tcad"
  end
end
