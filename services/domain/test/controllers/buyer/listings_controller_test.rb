require "test_helper"

class Buyer::ListingsControllerTest < ActionDispatch::IntegrationTest
  def setup
    @mueller = Property.create!(address: "100 Mueller Blvd", state: "listed", region: "Mueller",
                               list_price: 700_000, beds: 3, baths: 2.0, sqft: 1800,
                               photo_urls: ["https://example.test/a.jpg"], source_name: "Sample",
                               captured_at: Time.current)
    @tarry = Property.create!(address: "200 Tarry Ln", state: "listed", region: "Tarrytown",
                             list_price: 1_500_000, beds: 4, photo_urls: ["https://example.test/b.jpg"])
    @acquired = Property.create!(address: "300 Hidden St", state: "acquired", list_price: 500_000)
    Comp.create!(property: @mueller, region: "Mueller", address: "9 Comp", sale_price: 690_000, sale_date: Date.new(2026, 3, 1), source_name: "TCAD")
  end

  test "index is reachable without any login (public front door)" do
    get buyer_listings_path
    assert_response :success
    assert_select ".mk-card", minimum: 1
  end

  test "catalog frame breaks out of itself so clicking a card opens the full page" do
    get buyer_listings_path
    # Without target=_top, a card click navigates inside the catalog frame and
    # the detail page (no catalog frame) shows 'Content missing'.
    assert_match(/turbo-frame id="catalog" target="_top"/, @response.body)
  end

  test "the market banner offers a ZIP selector and shows the picked ZIP's snapshot" do
    MarketSnapshot.create!(area: "Austin 78704", zip: "78704", median_price: 830_000, source: "RentCast", as_of: Date.new(2026, 6, 4))
    MarketSnapshot.create!(area: "Austin 78731", zip: "78731", median_price: 1_150_000, source: "RentCast", as_of: Date.new(2026, 6, 4))

    get buyer_listings_path(zip: "78704")
    assert_response :success
    assert_select "turbo-frame#market select[name=zip]"   # the picker exists
    assert_select "turbo-frame#market option[value=78704]"
    assert_match "$830,000", @response.body                # the picked ZIP's median, not the other
  end

  test "Sell your home is reachable from the nav even when signed out" do
    get buyer_listings_path
    assert_select "a.mk-nav-link[href=?]", seller_home_path, text: "Sell your home"
  end

  test "index shows browsable listings but not acquired inventory" do
    get buyer_listings_path
    assert_match @mueller.address, @response.body
    assert_no_match(/300 Hidden St/, @response.body)
  end

  test "filtering by region narrows results" do
    get buyer_listings_path, params: { region: "Mueller" }
    assert_response :success
    assert_match @mueller.address, @response.body
    assert_no_match(/200 Tarry Ln/, @response.body)
  end

  test "price filter respects inclusive bounds" do
    get buyer_listings_path, params: { price_min: 700_000, price_max: 700_000 }
    assert_match @mueller.address, @response.body
    assert_no_match(/200 Tarry Ln/, @response.body)
  end

  test "empty result renders an empty state, not an error" do
    get buyer_listings_path, params: { region: "Nowhere" }
    assert_response :success
    assert_select ".mk-empty"
  end

  test "detail page renders photos, facts, comps and provenance" do
    get buyer_listing_path(@mueller)
    assert_response :success
    assert_match @mueller.address, @response.body
    assert_match "Recent nearby sales", @response.body
    assert_match "Sample", @response.body # provenance label
  end

  test "detail page offers real showing slots that post to the booking endpoint (R6)" do
    get buyer_listing_path(@mueller)
    assert_response :success
    assert_match "Schedule a showing", @response.body
    assert_select "form[action=?]", buyer_listing_showings_path(@mueller), minimum: 1
  end

  test "detail 404s for non-browsable properties" do
    get buyer_listing_path(@acquired)
    assert_response :not_found
  end
end
