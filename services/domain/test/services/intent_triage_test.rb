require "test_helper"

class IntentTriageTest < ActiveSupport::TestCase
  test "buyer with pre-approval and a near-term move is high-intent" do
    r = IntentTriage.call(signals: { "preapproval" => "true", "move_timeline_days" => "20" }, side: "buyer")
    assert r.high_intent?
    assert_equal "high_intent", r.intent
    assert_includes r.signals_used, "preapproval"
    assert_includes r.signals_used, "move_timeline_days"
  end

  test "buyer pre-approved but far-off move stays a looky-loo" do
    r = IntentTriage.call(signals: { "preapproval" => "true", "move_timeline_days" => "90" }, side: "buyer")
    assert_not r.high_intent?
    assert_match(/near-term/i, r.reason)
  end

  test "buyer near-term move but no pre-approval stays a looky-loo" do
    r = IntentTriage.call(signals: { "move_timeline_days" => "15" }, side: "buyer")
    assert_not r.high_intent?
    assert_match(/pre-approv/i, r.reason)
  end

  test "seller with address plus a timeline is high-intent" do
    r = IntentTriage.call(signals: { "address" => "1 Main St", "timeline" => "60 days" }, side: "seller")
    assert r.high_intent?
  end

  test "seller with only an address stays a looky-loo" do
    r = IntentTriage.call(signals: { "address" => "1 Main St" }, side: "seller")
    assert_not r.high_intent?
  end

  test "EQUAL SERVICE: a non-neutral (protected-class) signal cannot change the outcome" do
    base = { "preapproval" => "true", "move_timeline_days" => "20" }
    with_protected = base.merge("ethnicity" => "x", "family_status" => "kids", "zip_demographic" => "y")
    a = IntentTriage.call(signals: base, side: "buyer")
    b = IntentTriage.call(signals: with_protected, side: "buyer")
    assert_equal a.intent, b.intent
    assert_equal a.signals_used, b.signals_used # protected keys never appear as "used"
    assert_not_includes b.signals_used, "ethnicity"
  end

  test "signals_used lists only allow-list keys that are present" do
    r = IntentTriage.call(signals: { "preapproval" => "true" }, side: "buyer")
    assert_equal ["preapproval"], r.signals_used
  end
end
