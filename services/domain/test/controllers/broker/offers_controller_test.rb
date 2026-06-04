require "test_helper"

class Broker::OffersControllerTest < ActionDispatch::IntegrationTest
  def setup
    # Closer unreachable in tests -> ContractGeneration uses the Rails fallback,
    # so signing works end-to-end without a live brain.
    @lead = Lead.create!(side: "buyer", address: "1 Mueller", contact: "jordan@example.com")
    @offer = Offer.create!(lead: @lead, side: "buyer", amount: 625_000, status: "awaiting_broker",
      property: Property.create!(address: "1 Mueller", state: "listed", list_price: 625_000),
      form_json: { property_address: "1 Mueller", buyer_name: "Jordan", buyer_email: "jordan@example.com" }.to_json)
  end

  def sign_in_broker
    post session_path, params: { name: "Bea Broker", email: "broker@atlas.example" } # allowlisted
  end

  test "signing requires a broker; a non-broker cannot sign" do
    post session_path, params: { name: "Casey", email: "casey@example.com" }
    assert_no_difference -> { Contract.count } do
      post sign_broker_offer_path(@offer)
    end
    assert_redirected_to root_path
    assert_equal "awaiting_broker", @offer.reload.status
  end

  test "signing an offer marks it signed and delivers a contract draft to both parties" do
    sign_in_broker
    assert_difference -> { Contract.count }, 1 do
      post sign_broker_offer_path(@offer)
    end
    assert_redirected_to broker_dashboard_path
    assert_equal "signed", @offer.reload.status
    contract = @offer.contract
    assert_equal "draft", contract.status
    assert contract.delivered_at.present?
  end

  test "the buyer can view their delivered contract; a stranger cannot" do
    sign_in_broker
    post sign_broker_offer_path(@offer)
    contract = @offer.reload.contract
    delete session_path # broker signs out

    # The buyer (matching email) sees it.
    post session_path, params: { name: "Jordan", email: "jordan@example.com" }
    get contract_path(contract)
    assert_response :success
    assert_match "draft for review", @response.body

    # A different visitor cannot.
    delete session_path
    post session_path, params: { name: "Mallory", email: "mallory@example.com" }
    get contract_path(contract)
    assert_response :not_found
  end
end
