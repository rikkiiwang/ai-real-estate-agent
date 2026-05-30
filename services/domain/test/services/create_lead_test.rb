require "test_helper"

class CreateLeadTest < ActiveSupport::TestCase
  test "creates a lead from structured terms" do
    lead = CreateLead.call(side: "buyer", address: "20 Rio Grande", contact: "buyer@x.com")
    assert lead.persisted?
    assert_equal "buyer", lead.side
    assert_equal "unknown", lead.intent
  end

  test "raises on invalid side" do
    assert_raises(ActiveRecord::RecordInvalid) { CreateLead.call(side: "nope", address: "x") }
  end
end
