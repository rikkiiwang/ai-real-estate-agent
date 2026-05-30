require "test_helper"

class Broker::DashboardControllerTest < ActionDispatch::IntegrationTest
  test "renders the handoff queue and offers awaiting broker sign" do
    lead = Lead.create!(side: "seller", address: "40 Barton Springs", intent: "high")
    EnqueueHandoff.call(lead: lead, trigger: "legal_complexity", confidence: 0.2, reason: "custom clause")
    offer = lead.offers.create!(side: "seller", amount: 425_000)
    offer.enqueue_for_broker!

    get broker_dashboard_path
    assert_response :success
    assert_select "section#handoff-queue tr.handoff", 1
    assert_select "section#offers-awaiting-sign tr.offer", 1
    assert_match "legal_complexity", @response.body
  end

  test "shows empty states when queues are clear" do
    get broker_dashboard_path
    assert_response :success
    assert_select "section#handoff-queue p.empty"
    assert_select "section#offers-awaiting-sign p.empty"
  end
end
