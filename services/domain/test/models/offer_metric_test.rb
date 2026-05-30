require "test_helper"

class OfferMetricTest < ActiveSupport::TestCase
  setup do
    @seller_lead = Lead.create!(side: "seller", address: "10 Cedar", intent: "high")
    @buyer_lead = Lead.create!(side: "buyer", address: "22 Pecan", intent: "high")
  end

  test "a completed seller flow records a positive time-to-offer duration" do
    @seller_lead.update_column(:created_at, 90.seconds.ago)
    offer = @seller_lead.offers.create!(side: "seller", amount: 350_000)

    assert_difference -> { OfferMetric.count }, 1 do
      offer.enqueue_for_broker!
    end

    metric = offer.offer_metric
    assert_equal "seller", metric.side
    assert_equal @seller_lead, metric.lead
    assert_operator metric.seconds_to_offer, :>, 0
    assert_in_delta 90, metric.seconds_to_offer, 5
  end

  test "seller and buyer variants both record" do
    @seller_lead.offers.create!(side: "seller", amount: 350_000).enqueue_for_broker!
    @buyer_lead.offers.create!(side: "buyer", amount: 500_000).enqueue_for_broker!

    assert_equal %w[buyer seller], OfferMetric.pluck(:side).sort
  end

  test "an escalated/abandoned flow records no false completion" do
    # Lead escalates to a human (handoff) and the offer is never drafted past
    # 'drafting' — no offer-drafted moment, so no time-to-offer is recorded.
    HandoffPacket.create!(lead: @seller_lead, trigger: "legal_complexity", status: "pending")
    @seller_lead.offers.create!(side: "seller", amount: 350_000) # stays in 'drafting'

    assert_equal 0, OfferMetric.count
  end

  test "recording is idempotent per offer" do
    offer = @seller_lead.offers.create!(side: "seller", amount: 350_000)
    offer.enqueue_for_broker!
    assert_no_difference -> { OfferMetric.count } do
      OfferMetric.record_for(offer)
    end
  end

  test "summary reports per-side and aggregate stats" do
    @seller_lead.update_column(:created_at, 100.seconds.ago)
    @buyer_lead.update_column(:created_at, 200.seconds.ago)
    @seller_lead.offers.create!(side: "seller", amount: 350_000).enqueue_for_broker!
    @buyer_lead.offers.create!(side: "buyer", amount: 500_000).enqueue_for_broker!

    summary = OfferMetric.summary
    assert_equal 1, summary["seller"][:count]
    assert_equal 1, summary["buyer"][:count]
    assert_equal 2, summary["all"][:count]
    assert summary["seller"][:average_seconds].positive?
    assert_nil OfferMetric.stats_for([])[:average_seconds]
  end

  test "validates side and non-negative duration" do
    offer = @seller_lead.offers.create!(side: "seller", amount: 350_000)
    assert_not OfferMetric.new(offer: offer, lead: @seller_lead, side: "x",
                               seconds_to_offer: 10, recorded_at: Time.current).valid?
    assert_not OfferMetric.new(offer: offer, lead: @seller_lead, side: "seller",
                               seconds_to_offer: -1, recorded_at: Time.current).valid?
  end
end
