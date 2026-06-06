require "test_helper"

class Seller::ValuationsControllerTest < ActionDispatch::IntegrationTest
  class FakeClient
    def initialize(result)
      @result = result
    end

    def valuation(**)
      @result
    end
  end

  def use_valuation(result)
    Seller::ValuationsController.valuation_client_override = -> { FakeClient.new(result) }
    yield
  ensure
    Seller::ValuationsController.valuation_client_override = nil
  end

  def sign_in
    post session_path, params: { name: "Sam Seller", email: "sam@example.com" }
  end

  def usable
    BrainValuationClient::Result.new(sufficient_data: true, estimate: 615_000, low: 590_000, high: 640_000,
      facts: [BrainValuationClient::Fact.new(kind: "tcad_appraisal", description: "TCAD value $602k", source_id: "t1")], error: nil)
  end

  test "seller workspace requires login" do
    post seller_valuations_path, params: { address: "1 Main" }
    assert_redirected_to new_session_path
  end

  test "a usable valuation yields a cited cash offer and an awaiting_broker seller offer" do
    sign_in
    assert_difference -> { Offer.count }, 1 do
      use_valuation(usable) do
        post seller_valuations_path, params: { address: "1 Main St, Austin" }
      end
    end
    offer = Offer.last
    assert_equal "seller", offer.side
    assert_equal "awaiting_broker", offer.status
    assert_match "Preliminary cash offer", @response.body
    assert_match "county appraisal (TCAD)", @response.body # cited, friendly label
    # The result must be inside the seller-result Turbo frame, or a real browser
    # discards the 200 POST response and the result never appears.
    assert_match(/turbo-frame id="seller-result"/, @response.body)
  end

  test "insufficient data does not fabricate an offer (records a lead instead)" do
    sign_in
    insufficient = BrainValuationClient::Result.new(sufficient_data: false, estimate: 0, facts: [], error: nil)
    assert_no_difference -> { Offer.count } do
      assert_difference -> { Lead.count }, 1 do
        use_valuation(insufficient) do
          post seller_valuations_path, params: { address: "9 Unknown Rd" }
        end
      end
    end
    assert_match(/broker will follow up/i, @response.body)
  end

  test "a brain failure degrades gracefully, no offer, no 500" do
    sign_in
    down = BrainValuationClient::Result.new(sufficient_data: false, estimate: 0, facts: [], error: "valuation_unavailable")
    assert_no_difference -> { Offer.count } do
      use_valuation(down) do
        post seller_valuations_path, params: { address: "1 Main" }
      end
    end
    assert_response :success
    assert_match(/taking a moment/i, @response.body)
  end

  test "seller valuation surfaces freshness from the assembled valuation" do
    Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 500_000, sqft: 2000, beds: 4, baths: 2.5, year_built: 1998,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)
    MarketSnapshot.create!(zip: "78704", area: "Austin 78704", median_price: 600_000,
                           new_listings: 3, avg_days_on_market: 21, as_of: Date.new(2026, 6, 5))
    sign_in

    # Inject a client that echoes the freshness metadata back so the view can render it.
    freshness_client = Class.new do
      def valuation(address:, features: nil, comps: nil, as_of: nil, recent_activity: nil, **)
        BrainValuationClient::Result.new(
          sufficient_data: true, estimate: 480_000, low: 440_000, high: 520_000,
          facts: [], as_of: as_of, recent_activity: recent_activity, error: nil
        )
      end
    end.new

    Seller::ValuationsController.valuation_client_override = -> { freshness_client }
    post seller_valuations_path, params: { address: "1 Oak St" }
    Seller::ValuationsController.valuation_client_override = nil

    assert_response :success
    assert_match(/new listing/i, @response.body)    # recent_activity surfaced
    assert_match(/as of/i, @response.body)          # freshness label surfaced
  end
end
