require "test_helper"

class Broker::DashboardControllerTest < ActionDispatch::IntegrationTest
  BROKER_EMAIL = "broker@atlas.example".freeze # on the allowlist in config/marketplace.yml

  def sign_in_broker
    post session_path, params: { name: "Bea Broker", email: BROKER_EMAIL }
  end

  def sign_in_consumer
    post session_path, params: { name: "Casey Consumer", email: "casey@example.com" }
  end

  test "renders the handoff queue and offers awaiting broker sign" do
    sign_in_broker
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
    sign_in_broker
    get broker_dashboard_path
    assert_response :success
    assert_select "section#handoff-queue p.empty"
    assert_select "section#offers-awaiting-sign p.empty"
  end

  test "a signed-out visitor is sent to sign in" do
    get broker_dashboard_path
    assert_redirected_to new_session_path
  end

  test "a non-broker visitor cannot reach the console (server-side gate)" do
    sign_in_consumer
    get broker_dashboard_path
    assert_redirected_to root_path
  end

  test "the Dashboard tab shows only for brokers" do
    sign_in_consumer
    get buyer_listings_path
    assert_select "a.mk-nav-link--broker", false, "consumers must not see the broker tab"

    delete session_path
    sign_in_broker
    get buyer_listings_path
    assert_select "a.mk-nav-link--broker", text: "Dashboard"
  end

  test "surfaces time-to-offer per side and aggregate" do
    sign_in_broker
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
