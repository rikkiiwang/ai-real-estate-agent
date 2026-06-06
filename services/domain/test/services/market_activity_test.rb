# services/domain/test/services/market_activity_test.rb
require "test_helper"

class MarketActivityTest < ActiveSupport::TestCase
  test "summarizes new listings and as_of from the ZIP snapshot" do
    MarketSnapshot.create!(zip: "78704", area: "Austin 78704", median_price: 600_000,
                           avg_price_per_sqft: 320, new_listings: 3,
                           avg_days_on_market: 21, as_of: Date.new(2026, 6, 5))

    a = MarketActivity.new(region: "Austin 78704").call

    assert_equal Date.new(2026, 6, 5), a.as_of.to_date
    assert_match(/3 new listing/, a.summary)
    assert_match(/21/, a.summary) # days on market surfaced
  end

  test "honest empty summary when no snapshot exists" do
    a = MarketActivity.new(region: "Austin 99999").call
    assert_nil a.as_of
    assert_match(/no recent market data/i, a.summary)
  end
end
