require "test_helper"

class ListingPageSlimTest < ActionDispatch::IntegrationTest
  setup do
    @l = Property.create!(address: "9 Demo St, Austin TX 78704", state: "listed", region: "Zilker",
                          list_price: 625_000, sqft: 1850, beds: 3, baths: 2,
                          photo_urls: ["https://example.test/a.jpg"], source_name: "S", captured_at: Time.current)
    MarketSnapshot.create!(zip: "78704", area: "Zilker", median_price: 700_000, avg_price_per_sqft: 380, avg_days_on_market: 18, as_of: Time.current)
    PhotoAnalysis.create!(address: @l.address, property: @l, analyzed_at: Time.current, condition: 0.7, provenance: "sample",
                          findings: [{ "kind" => "feature", "label" => "updated_kitchen", "confidence" => 0.9, "evidence_photo_id" => "a" }])
  end

  test "analysis cards are removed; schedule + offer stay" do
    get buyer_listing_path(@l)
    assert_response :success
    assert_select "#neighborhood-pulse", false
    assert_select "#photo-analysis", false
    assert_select "h2", text: "Recent nearby sales", count: 0
    assert_select "#schedule-showing"                      # interactive widget stays
    assert_select "a", text: "Make an offer →"
  end
end
