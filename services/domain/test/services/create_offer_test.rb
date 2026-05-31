require "test_helper"

class CreateOfferTest < ActiveSupport::TestCase
  def setup
    @lead = Lead.create!(side: "seller", address: "123 Congress Ave, Austin TX", contact: "s@example.com")
  end

  test "creates an offer in the awaiting-broker queue (never signed)" do
    offer = CreateOffer.call(lead: @lead, side: "seller", amount: 470_000)

    assert offer.persisted?
    assert_equal "awaiting_broker", offer.status
    assert_not_equal "signed", offer.status
    assert_includes Offer.awaiting_broker_sign, offer
  end

  test "records a time-to-offer metric when enqueued" do
    assert_difference -> { OfferMetric.count }, 1 do
      CreateOffer.call(lead: @lead, side: "seller", amount: 470_000)
    end
  end

  test "associates an existing property by address, nil otherwise" do
    prop = Property.create!(address: "500 W 2nd St, Austin TX", state: "listed")
    matched = CreateOffer.call(lead: @lead, side: "buyer", amount: 480_000, property_address: prop.address)
    assert_equal prop, matched.property

    unmatched = CreateOffer.call(lead: @lead, side: "seller", amount: 460_000, property_address: "999 Nowhere Rd")
    assert_nil unmatched.property
  end

  test "persists the filled-form json" do
    offer = CreateOffer.call(lead: @lead, side: "seller", amount: 470_000, form_json: '{"price":470000}')
    assert_equal '{"price":470000}', offer.reload.form_json
  end
end
