require "test_helper"

class ClosingMilestoneTest < ActiveSupport::TestCase
  def offer
    lead = Lead.create!(side: "buyer", address: "1 A St", contact: "b@x.com", intent: "high")
    Offer.create!(lead: lead, side: "buyer", status: "signed")
  end

  test "milestone is unique per offer" do
    o = offer
    o.closing_milestones.create!(milestone: "inspection_cleared", ping_status: "simulated", recorded_at: Time.current)
    dup = o.closing_milestones.build(milestone: "inspection_cleared", ping_status: "simulated", recorded_at: Time.current)
    assert_not dup.valid?
  end

  test "rejects an unknown milestone or ping_status" do
    o = offer
    assert_not o.closing_milestones.build(milestone: "nope", ping_status: "simulated", recorded_at: Time.current).valid?
    assert_not o.closing_milestones.build(milestone: "funded", ping_status: "weird", recorded_at: Time.current).valid?
  end

  test "Offer tracks order, next milestone, and completion" do
    o = offer
    assert_equal "deal-#{o.id}", o.deal_id
    assert_equal "inspection_cleared", o.next_closing_milestone
    %w[inspection_cleared earnest_deposited title_cleared funded].each do |m|
      o.closing_milestones.create!(milestone: m, ping_status: "simulated", recorded_at: Time.current)
    end
    assert_nil o.reload.next_closing_milestone
    assert o.closing_complete?
  end
end
