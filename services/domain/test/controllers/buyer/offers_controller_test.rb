require "test_helper"

class Buyer::OffersControllerTest < ActionDispatch::IntegrationTest
  def setup
    @listing = Property.create!(address: "1 Mueller", state: "listed", region: "Mueller", list_price: 625_000,
                              beds: 3, baths: 2.0, sqft: 1800, photo_urls: ["x"])
    Comp.create!(region: "Mueller", address: "9 Comp", sale_price: 612_000, sale_date: Date.new(2026, 3, 1), source_name: "TCAD")
  end

  def sign_in
    post session_path, params: { name: "Jordan", email: "jordan@example.com" }
  end

  test "the offer page requires login" do
    get new_buyer_listing_offer_path(@listing)
    assert_redirected_to new_session_path
  end

  test "signed-in buyer sees the cited decision bundle" do
    sign_in
    get new_buyer_listing_offer_path(@listing)
    assert_response :success
    assert_match "Estimated monthly payment", @response.body
    assert_match "Freddie Mac PMMS", @response.body        # rate source
    assert_match "Travis County", @response.body           # tax source
    assert_match "Nearby recent sales", @response.body
  end

  test "custom assumptions flow through to the bundle" do
    sign_in
    get new_buyer_listing_offer_path(@listing), params: { offer_amount: 700_000, down_payment_pct: 10 }
    assert_response :success
    assert_match "$700,000", @response.body
  end
end
