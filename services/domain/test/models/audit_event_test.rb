require "test_helper"

class AuditEventTest < ActiveSupport::TestCase
  test "records a claim->source decision" do
    event = AuditEvent.record_claim_decision(
      claim: "Home has granite countertops",
      source_id: "photo:abc123",
      decision: "entailed"
    )
    assert event.persisted?
    assert_equal "claim_source_decision", event.kind
  end

  test "is append-only: update raises" do
    event = AuditEvent.record_rail_trip(kind: "fair_housing_trip", decision: "blocked")
    assert_raises(ActiveRecord::ReadOnlyRecord) { event.update!(decision: "allowed") }
    assert_raises(ActiveRecord::ReadOnlyRecord) { event.decision = "allowed"; event.save! }
  end

  test "is append-only: destroy raises" do
    event = AuditEvent.record_rail_trip(kind: "fair_housing_trip", decision: "blocked")
    assert_raises(ActiveRecord::ReadOnlyRecord) { event.destroy }
    assert AuditEvent.exists?(event.id)
  end

  test "links to a subject" do
    lead = Lead.create!(side: "buyer", address: "12 Ash")
    event = AuditEvent.record_claim_decision(claim: "c", source_id: "s", decision: "entailed", subject: lead)
    assert_equal "Lead", event.subject_type
    assert_equal lead.id.to_s, event.subject_id
  end

  test "maintains an intact prev_hash chain across appends" do
    AuditEvent.record_rail_trip(kind: "fair_housing_trip", decision: "blocked")
    AuditEvent.record_claim_decision(claim: "x", source_id: "y", decision: "entailed")
    AuditEvent.record_rail_trip(kind: "confidence_handoff", decision: "escalated")
    assert AuditEvent.chain_intact?

    first = AuditEvent.order(:id).first
    assert_nil first.prev_hash
    second = AuditEvent.order(:id).second
    assert_equal first.content_hash, second.prev_hash
  end
end
