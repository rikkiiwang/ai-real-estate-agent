require "test_helper"

class NegotiationResponseTest < ActiveSupport::TestCase
  def seller_offer(cash_offer: 480_000, estimate: 500_000)
    lead = Lead.create!(side: "seller", address: "1 Cedar", contact: "sam@example.com", intent: "high")
    Offer.create!(lead: lead, side: "seller", amount: cash_offer, status: "awaiting_broker",
      form_json: { property_address: "1 Cedar", cash_offer: cash_offer, valuation_estimate: estimate }.to_json)
  end

  test "a counter within the band is auto-accepted and updates the offer" do
    offer = seller_offer(cash_offer: 480_000, estimate: 500_000)
    result = NegotiationResponse.counter(offer: offer, counter_amount: 495_000)

    assert result.within_band
    assert result.accepted
    assert_equal 495_000, offer.reload.amount
    assert_equal 1, offer.negotiations.count
    assert offer.negotiations.last.within_band
    assert_match(/can meet/i, result.message)
  end

  test "a counter above the ceiling is recorded and escalated to a broker" do
    offer = seller_offer(cash_offer: 480_000, estimate: 500_000)
    assert_difference -> { HandoffPacket.count }, 1 do
      result = NegotiationResponse.counter(offer: offer, counter_amount: 560_000)
      assert_not result.within_band
      assert_not result.accepted
      assert_match(/licensed broker/i, result.message)
    end
    # The counter is recorded (not discarded) and the offer amount is unchanged.
    assert_equal 480_000, offer.reload.amount
    neg = offer.negotiations.last
    assert_not neg.within_band
    assert_equal 560_000, neg.counter_amount
    assert_equal "high_dollar", HandoffPacket.last.trigger
  end

  test "the ceiling is the valuation estimate, not the discounted cash offer" do
    offer = seller_offer(cash_offer: 480_000, estimate: 500_000)
    # 500_000 == ceiling -> still in band (inclusive).
    result = NegotiationResponse.counter(offer: offer, counter_amount: 500_000)
    assert result.accepted
  end
end
