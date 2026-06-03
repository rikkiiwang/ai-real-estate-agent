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

  test "AE2: submitting an offer records an awaiting_broker buyer offer in the queue" do
    sign_in
    assert_difference -> { Offer.count }, 1 do
      post buyer_listing_offer_path(@listing), params: { offer_amount: 625_000, down_payment_pct: 20 }
    end
    offer = Offer.last
    assert_equal "buyer", offer.side
    assert_equal "awaiting_broker", offer.status
    assert_equal @listing, offer.property
    assert_includes Offer.awaiting_broker_sign, offer
  end

  test "submitting records a time-to-offer metric once (idempotent enqueue)" do
    sign_in
    assert_difference -> { OfferMetric.count }, 1 do
      post buyer_listing_offer_path(@listing), params: { offer_amount: 625_000 }
    end
  end

  test "the buyer sees a not-binding, routed-for-review confirmation" do
    sign_in
    post buyer_listing_offer_path(@listing), params: { offer_amount: 625_000 }
    follow_redirect!
    assert_match(/routed to a licensed broker/i, @response.body)
    assert_match(/binding yet/i, @response.body)
  end

  test "the offer's form_json captures factual blanks (no clauses)" do
    sign_in
    post buyer_listing_offer_path(@listing), params: { offer_amount: 625_000, down_payment_pct: 20 }
    blanks = JSON.parse(Offer.last.form_json)
    assert_equal @listing.address, blanks["property_address"]
    assert_equal 625_000, blanks["offer_amount"]
    assert_equal "jordan@example.com", blanks["buyer_email"]
    assert_nil blanks["clause"] # UPL boundary: factual blanks only
  end

  test "making an offer requires login" do
    assert_no_difference -> { Offer.count } do
      post buyer_listing_offer_path(@listing), params: { offer_amount: 625_000 }
    end
    assert_redirected_to new_session_path
  end
end
