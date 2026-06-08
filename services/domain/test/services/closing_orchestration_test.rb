require "test_helper"

class ClosingOrchestrationTest < ActiveSupport::TestCase
  class OkClient
    def record_milestone(deal_id:, milestone:)
      ClosingClient::Result.new(pinged: true, counterparty: "escrow",
                                message: "Notified escrow: ... for #{deal_id}.", error: nil)
    end
  end

  class DownClient
    def record_milestone(deal_id:, milestone:)
      ClosingClient::Result.new(pinged: false, error: "closing_unavailable")
    end
  end

  def signed_offer
    lead = Lead.create!(side: "buyer", address: "1 A St", contact: "b@x.com", intent: "high")
    Offer.create!(lead: lead, side: "buyer", status: "signed")
  end

  test "records the next milestone, pings via the brain, and audits it" do
    o = signed_offer
    assert_difference -> { AuditEvent.count }, 1 do
      res = ClosingOrchestration.record(offer: o, milestone: "inspection_cleared", client: OkClient.new)
      assert res.recorded?
      assert_equal "escrow", res.counterparty
      assert_equal "simulated", res.ping_status
    end
    cm = o.closing_milestones.find_by(milestone: "inspection_cleared")
    assert_equal "simulated", cm.ping_status
    assert_equal "milestone_recorded", AuditEvent.order(:id).last.kind
  end

  test "is idempotent — re-recording a met milestone is a no-op" do
    o = signed_offer
    ClosingOrchestration.record(offer: o, milestone: "inspection_cleared", client: OkClient.new)
    assert_no_difference -> { ClosingMilestone.count } do
      res = ClosingOrchestration.record(offer: o, milestone: "inspection_cleared", client: OkClient.new)
      assert_not res.recorded?
      assert_equal "already recorded", res.reason
    end
  end

  test "enforces canonical order" do
    o = signed_offer
    res = ClosingOrchestration.record(offer: o, milestone: "funded", client: OkClient.new)
    assert_not res.recorded?
    assert_match(/inspection_cleared first/, res.reason)
    assert_equal 0, o.closing_milestones.count
  end

  test "brain-down still records the milestone, marked pending via local routing" do
    o = signed_offer
    res = ClosingOrchestration.record(offer: o, milestone: "inspection_cleared", client: DownClient.new)
    assert res.recorded?
    assert_equal "escrow", res.counterparty       # from RAILS_ROUTING
    assert_equal "pending", res.ping_status
    assert_equal "pending", o.closing_milestones.first.ping_status
  end
end
