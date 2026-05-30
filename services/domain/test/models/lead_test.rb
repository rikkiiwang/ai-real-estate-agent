require "test_helper"

class LeadTest < ActiveSupport::TestCase
  test "valid seller lead persists" do
    lead = Lead.create!(side: "seller", address: "123 Main St, Austin", contact: "a@b.com", intent: "high")
    assert lead.persisted?
  end

  test "requires a valid side" do
    lead = Lead.new(side: "neither", address: "1 St")
    assert_not lead.valid?
    assert_includes lead.errors[:side], "is not included in the list"
  end

  test "requires an address" do
    assert_not Lead.new(side: "buyer").valid?
  end

  test "intent defaults to unknown and rejects bad values" do
    lead = Lead.create!(side: "buyer", address: "5 Oak")
    assert_equal "unknown", lead.intent
    lead.intent = "maybe"
    assert_not lead.valid?
  end

  test "has many offers and handoff packets" do
    lead = Lead.create!(side: "seller", address: "9 Elm")
    lead.offers.create!(side: "seller", status: "drafting")
    lead.handoff_packets.create!(trigger: "legal_complexity")
    assert_equal 1, lead.offers.count
    assert_equal 1, lead.handoff_packets.count
  end
end
