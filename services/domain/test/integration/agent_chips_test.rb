require "test_helper"

class AgentChipsTest < ActionDispatch::IntegrationTest
  test "the listing page renders Atlas suggested-prompt chips" do
    l = Property.create!(address: "9 Demo St, Austin TX 78704", state: "listed", region: "Zilker",
                         list_price: 625_000, sqft: 1850, beds: 3, baths: 2,
                         photo_urls: ["https://example.test/a.jpg"], source_name: "S", captured_at: Time.current)
    get buyer_listing_path(l)
    assert_response :success
    assert_select "[data-insight='neighborhood']"
    assert_select "[data-insight='photos']"
    assert_select "[data-insight='price']"
    assert_select "[data-insight='tour']"
  end
end
