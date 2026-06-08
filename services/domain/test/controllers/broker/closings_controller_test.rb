require "test_helper"

class Broker::ClosingsControllerTest < ActionDispatch::IntegrationTest
  def sign_in_broker
    post session_path, params: { name: "Bro", email: "broker@atlas.example" }
  end

  def signed_offer
    lead = Lead.create!(side: "buyer", address: "9 Deal St", contact: "b@x.com", intent: "high")
    Offer.create!(lead: lead, side: "buyer", status: "signed",
                  property: Property.create!(address: "9 Deal St", state: "listed", list_price: 500_000))
  end

  test "broker records the next milestone and the brain-down path still works" do
    sign_in_broker
    o = signed_offer
    # No brain reachable in test → ClosingClient errors → pending path.
    assert_difference -> { ClosingMilestone.count }, 1 do
      post record_milestone_broker_offer_path(o), params: { milestone: "inspection_cleared" }
    end
    assert_redirected_to broker_dashboard_path
    assert_equal "inspection_cleared", o.closing_milestones.first.milestone
  end

  test "the dashboard shows the closing pipeline tracker for a signed deal" do
    sign_in_broker
    o = signed_offer
    o.closing_milestones.create!(milestone: "inspection_cleared", counterparty: "escrow",
                                 ping_status: "simulated", recorded_at: Time.current)
    get broker_dashboard_path
    assert_response :success
    assert_select "#closing-deals"
    assert_match(/Inspection cleared/i, @response.body)
    assert_match(/Escrow officer/i, @response.body)
  end

  test "out-of-order recording is refused with an alert" do
    sign_in_broker
    o = signed_offer
    post record_milestone_broker_offer_path(o), params: { milestone: "funded" }
    assert_redirected_to broker_dashboard_path
    assert_equal 0, o.closing_milestones.count
  end
end
