require "test_helper"

class OfferTest < ActiveSupport::TestCase
  setup do
    @lead = Lead.create!(side: "seller", address: "10 Cedar", intent: "high")
  end

  test "persists with lead association and optional property" do
    offer = @lead.offers.create!(side: "seller", amount: 350_000)
    assert offer.persisted?
    assert_nil offer.property
    assert_equal "drafting", offer.status
  end

  test "rejects bad side and status" do
    assert_not Offer.new(lead: @lead, side: "x", status: "drafting").valid?
    assert_not Offer.new(lead: @lead, side: "seller", status: "x").valid?
  end

  test "rejects non-positive amount" do
    assert_not Offer.new(lead: @lead, side: "seller", status: "drafting", amount: 0).valid?
  end

  test "enqueue_for_broker! puts offer in the awaiting-broker queue" do
    offer = @lead.offers.create!(side: "seller", amount: 400_000)
    assert_empty Offer.awaiting_broker_sign
    offer.enqueue_for_broker!
    assert offer.awaiting_broker_sign?
    assert_includes Offer.awaiting_broker_sign, offer
  end

  test "signed offers leave the queue" do
    offer = @lead.offers.create!(side: "buyer", amount: 500_000, status: "awaiting_broker")
    assert_includes Offer.awaiting_broker_sign, offer
    offer.sign!
    assert_not_includes Offer.awaiting_broker_sign, offer
  end
end
