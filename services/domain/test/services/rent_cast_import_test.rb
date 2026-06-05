require "test_helper"

class RentCastImportTest < ActiveSupport::TestCase
  # A fake RentCast client returning canned API-shaped payloads.
  class FakeClient
    def initialize(listings:, markets: {})
      @listings = listings
      @markets = markets
    end

    def configured? = true
    def sale_listings(**) = @listings
    def market(zip:) = @markets[zip]
  end

  def listing(addr:, price:, beds:, baths:, sqft:, zip:, type: "Single Family")
    { "formattedAddress" => addr, "price" => price, "bedrooms" => beds, "bathrooms" => baths,
      "squareFootage" => sqft, "yearBuilt" => 1990, "zipCode" => zip, "propertyType" => type,
      "latitude" => 30.2, "longitude" => -97.7 }
  end

  test "imports residential listings as browsable properties with RentCast provenance" do
    client = FakeClient.new(listings: [
      listing(addr: "1 Real St, Austin, TX 78704", price: 700_000, beds: 3, baths: 2, sqft: 1800, zip: "78704"),
      listing(addr: "2 Real St, Austin, TX 78723", price: 550_000, beds: 3, baths: 2, sqft: 1400, zip: "78723")
    ])
    result = RentCastImport.new(client).call

    assert_equal 2, result.imported
    p = Property.find_by(address: "1 Real St, Austin, TX 78704")
    assert_equal "listed", p.state
    assert_equal 700_000, p.list_price.to_i
    assert_equal "Austin 78704", p.region
    assert_match "RentCast", p.source_name
    assert p.photo_urls.any? # sample imagery (RentCast licenses none)
    assert_includes Property.browsable, p
  end

  test "skips non-residential rows (no beds/baths/sqft)" do
    client = FakeClient.new(listings: [
      { "formattedAddress" => "Lot 9, Austin, TX", "price" => 1_000_000, "propertyType" => "Land", "zipCode" => "78724" }
    ])
    assert_equal 0, RentCastImport.new(client).call.imported
  end

  test "caches market snapshots per zip" do
    client = FakeClient.new(
      listings: [listing(addr: "1 Real St, Austin, TX 78704", price: 700_000, beds: 3, baths: 2, sqft: 1800, zip: "78704")],
      markets: { "78704" => { "medianPrice" => 829_900, "averagePricePerSquareFoot" => 576.2,
                              "totalListings" => 614, "newListings" => 40, "averageDaysOnMarket" => 75.66,
                              "lastUpdatedDate" => "2026-06-04T00:00:00.000Z" } }
    )
    result = RentCastImport.new(client).call
    assert_equal 1, result.snapshots
    snap = MarketSnapshot.headline
    assert_equal "Austin 78704", snap.area
    assert_equal 829_900, snap.median_price.to_i
    assert_equal Date.new(2026, 6, 4), snap.as_of
  end

  test "snapshots the curated ZIP set even for ZIPs with no listing in the batch" do
    # One listing in 78704, but market data exists for curated ZIPs that have NO
    # listing here (78702, 78731) — they must still be snapshotted for the banner.
    mkt = { "medianPrice" => 600_000, "averagePricePerSquareFoot" => 400.0,
            "totalListings" => 100, "newListings" => 5, "averageDaysOnMarket" => 30.0,
            "lastUpdatedDate" => "2026-06-04T00:00:00.000Z" }
    client = FakeClient.new(
      listings: [listing(addr: "1 Real St, Austin, TX 78704", price: 700_000, beds: 3, baths: 2, sqft: 1800, zip: "78704")],
      markets: { "78704" => mkt, "78702" => mkt, "78731" => mkt }
    )
    result = RentCastImport.new(client).call
    assert_equal 3, result.snapshots
    assert_equal %w[78702 78704 78731], MarketSnapshot.order(:zip).pluck(:zip)
  end

  test "an explicit market_zips list overrides the curated default" do
    mkt = { "medianPrice" => 500_000, "lastUpdatedDate" => "2026-06-04T00:00:00.000Z" }
    client = FakeClient.new(listings: [], markets: { "78745" => mkt, "78704" => mkt })
    result = RentCastImport.new(client).call(market_zips: ["78745"])
    assert_equal 1, result.snapshots
    assert_equal ["78745"], MarketSnapshot.pluck(:zip)  # 78704 not requested -> not snapshotted
  end

  test "is idempotent (re-import upserts, no duplicates)" do
    client = FakeClient.new(listings: [listing(addr: "1 Real St, Austin, TX 78704", price: 700_000, beds: 3, baths: 2, sqft: 1800, zip: "78704")])
    RentCastImport.new(client).call
    assert_no_difference "Property.count" do
      RentCastImport.new(client).call
    end
  end

  def four_listings(*zips_prices)
    zips_prices.each_with_index.map do |(zip, price), i|
      listing(addr: "#{i} Feed St, Austin, TX #{zip}", price: price, beds: 3, baths: 2, sqft: 1500, zip: zip)
    end
  end

  test "retires RentCast listings that drop out of the active feed" do
    full = four_listings(["78704", 700_000], ["78702", 600_000], ["78723", 500_000], ["78745", 800_000])
    RentCastImport.new(FakeClient.new(listings: full)).call
    assert_equal 4, Property.browsable.count

    # Next import: the 500k home is gone from the feed. It must be retired —
    # no longer browsable, and flagged retired_at — not silently kept as "Live".
    shrunk = full.reject { |l| l["price"] == 500_000 }
    result = RentCastImport.new(FakeClient.new(listings: shrunk)).call
    assert_equal 1, result.retired
    assert_equal 3, Property.browsable.count
    gone = Property.find_by(address: "2 Feed St, Austin, TX 78723")
    assert_not_nil gone.retired_at
    assert_not_includes Property.browsable, gone
  end

  test "a reappearing listing is reactivated (retired_at cleared)" do
    full = four_listings(["78704", 700_000], ["78702", 600_000], ["78723", 500_000], ["78745", 800_000])
    RentCastImport.new(FakeClient.new(listings: full)).call
    RentCastImport.new(FakeClient.new(listings: full.first(3))).call # 800k drops, retired
    gone = Property.find_by(address: "3 Feed St, Austin, TX 78745")
    assert_not_nil gone.retired_at

    RentCastImport.new(FakeClient.new(listings: full)).call # it's back in the feed
    assert_nil gone.reload.retired_at
    assert_includes Property.browsable, gone
  end

  test "a thin/transient feed does NOT mass-retire the catalog" do
    full = four_listings(["78704", 700_000], ["78702", 600_000], ["78723", 500_000], ["78745", 800_000])
    RentCastImport.new(FakeClient.new(listings: full)).call

    # An API hiccup returns just one listing (< half of 4). Retirement is skipped
    # so the other three stay browsable rather than vanishing.
    result = RentCastImport.new(FakeClient.new(listings: full.first(1))).call
    assert_equal 0, result.retired
    assert_equal 4, Property.browsable.count
  end

  test "an unconfigured client imports nothing" do
    unconfigured = Class.new { def configured? = false }.new
    assert_equal 0, RentCastImport.new(unconfigured).call.imported
  end
end
