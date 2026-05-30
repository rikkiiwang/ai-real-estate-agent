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

  test "surfaces time-to-offer per side and aggregate" do
    seller = Lead.create!(side: "seller", address: "12 Cedar", intent: "high")
    buyer = Lead.create!(side: "buyer", address: "9 Pecan", intent: "high")
    seller.update_column(:created_at, 60.seconds.ago)
    buyer.update_column(:created_at, 120.seconds.ago)
    seller.offers.create!(side: "seller", amount: 350_000).enqueue_for_broker!
    buyer.offers.create!(side: "buyer", amount: 500_000).enqueue_for_broker!

    get broker_dashboard_path
    assert_response :success
    assert_select "section#time-to-offer tr.time-to-offer", 3 # seller, buyer, all
    assert_select "section#time-to-offer tr[data-side=seller] td.count", "1"
    assert_select "section#time-to-offer tr[data-side=buyer] td.count", "1"
    assert_select "section#time-to-offer tr[data-side=all] td.count", "2"
  end
end
