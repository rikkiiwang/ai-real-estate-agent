require "test_helper"

class Seller::CountersControllerTest < ActionDispatch::IntegrationTest
  def sign_in(email = "sam@example.com")
    post session_path, params: { name: "Sam Seller", email: email }
  end

  def seller_offer(email: "sam@example.com", cash_offer: 480_000, estimate: 500_000)
    lead = Lead.create!(side: "seller", address: "1 Cedar", contact: email, intent: "high")
    Offer.create!(lead: lead, side: "seller", amount: cash_offer, status: "awaiting_broker",
      form_json: { property_address: "1 Cedar", cash_offer: cash_offer, valuation_estimate: estimate }.to_json)
  end

  test "counters require login" do
    offer = seller_offer
    post seller_counters_path, params: { offer_id: offer.id, counter_amount: 495_000 }
    assert_redirected_to new_session_path
  end

  test "an in-band counter is accepted and shown" do
    offer = seller_offer
    sign_in
    post seller_counters_path, params: { offer_id: offer.id, counter_amount: 495_000 }
    assert_response :success
    assert_equal 495_000, offer.reload.amount
    assert_match(/accepted/i, @response.body)
  end

  test "an above-band counter escalates to a broker" do
    offer = seller_offer
    sign_in
    assert_difference -> { HandoffPacket.count }, 1 do
      post seller_counters_path, params: { offer_id: offer.id, counter_amount: 560_000 }
    end
    assert_match(/routed to a broker/i, @response.body)
  end

  test "a seller cannot counter another seller's offer" do
    other = seller_offer(email: "someone@else.com")
    sign_in("sam@example.com")
    post seller_counters_path, params: { offer_id: other.id, counter_amount: 495_000 }
    assert_response :not_found
  end
end
