require "test_helper"

class NegotiationTest < ActiveSupport::TestCase
  setup do
    lead = Lead.create!(side: "seller", address: "11 Birch", intent: "high")
    @offer = lead.offers.create!(side: "seller", amount: 300_000)
  end

  test "counter within band is flagged within_band" do
    neg = @offer.negotiations.create!(counter_amount: 310_000, band_low: 290_000, band_high: 320_000)
    assert neg.within_band?
    assert neg.within_band
  end

  test "counter outside band is recorded but flagged out of band" do
    neg = @offer.negotiations.create!(counter_amount: 350_000, band_low: 290_000, band_high: 320_000)
    assert neg.persisted?
    assert_not neg.within_band
  end

  test "rejects malformed band" do
    neg = Negotiation.new(offer: @offer, counter_amount: 300_000, band_low: 320_000, band_high: 290_000)
    assert_not neg.valid?
  end
end
