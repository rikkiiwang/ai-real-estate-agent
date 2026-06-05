require "test_helper"

class VisitorTest < ActiveSupport::TestCase
  test "requires name and a valid email" do
    assert_not Visitor.new(name: "", email: "x@y.com").valid?
    assert_not Visitor.new(name: "Jo", email: "not-an-email").valid?
    assert Visitor.new(name: "Jo", email: "jo@example.com").valid?
  end

  test "normalizes and de-dupes email case-insensitively" do
    Visitor.create!(name: "Jo", email: "Jo@Example.com")
    dup = Visitor.new(name: "Jo2", email: "jo@example.com")
    assert_not dup.valid?
  end

  test "sign_in creates a new visitor" do
    visitor = Visitor.sign_in(name: "Pat", email: "pat@example.com")
    assert visitor.persisted?
    assert_equal "pat@example.com", visitor.email
  end

  test "sign_in returns the existing visitor for a known email" do
    first = Visitor.sign_in(name: "Pat", email: "pat@example.com")
    again = Visitor.sign_in(name: "Pat", email: "PAT@example.com")
    assert_equal first.id, again.id
  end

  test "sign_in with a bad email does not persist" do
    visitor = Visitor.sign_in(name: "Pat", email: "nope")
    assert_not visitor.persisted?
  end

  # --- intent triaging on the profile (R5) ---

  def buyer = Visitor.sign_in(name: "Bea Buyer", email: "bea@example.com")

  test "record_engagement triages from neutral signals and caches intent on the profile" do
    v = buyer
    t = v.record_engagement(signals: { "preapproval" => "true", "move_timeline_days" => "20" }, side: "buyer")
    assert t.high_intent?
    assert v.reload.high_intent?
    assert_equal "true", v.engagement_signals["preapproval"]
  end

  test "an unqualified buyer stays a looky-loo and routes no handoff" do
    v = buyer
    assert_no_difference "HandoffPacket.count" do
      assert_not v.record_engagement(signals: { "move_timeline_days" => "90" }, side: "buyer").high_intent?
    end
    assert_not v.reload.high_intent?
  end

  test "becoming high-intent routes exactly one broker handoff (idempotent)" do
    v = buyer
    assert_difference "HandoffPacket.queue.count", 1 do
      v.record_engagement(signals: { "preapproval" => "true", "move_timeline_days" => "20" }, side: "buyer")
    end
    assert_equal "high_intent", HandoffPacket.queue.first.trigger
    assert_no_difference "HandoffPacket.count" do
      v.record_engagement(signals: { "move_timeline_days" => "10" }, side: "buyer")
    end
  end

  test "EQUAL SERVICE: a protected-class signal is neither stored nor able to change triage" do
    v = buyer
    v.record_engagement(signals: { "preapproval" => "true", "move_timeline_days" => "20", "ethnicity" => "z" }, side: "buyer")
    assert v.reload.high_intent? # outcome unaffected by the protected key
    assert_not v.engagement_signals.key?("ethnicity") # and it was never stored
  end
end
