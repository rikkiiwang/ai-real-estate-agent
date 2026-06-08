require "test_helper"

class Buyer::ProfilesControllerTest < ActionDispatch::IntegrationTest
  def sign_in(v) = post(session_path, params: { name: v.name, email: v.email })

  test "edit requires a signed-in visitor" do
    get edit_buyer_profile_path
    assert_redirected_to new_session_path
  end

  test "update persists the profile and re-triages to high-intent" do
    v = Visitor.create!(name: "Bea", email: "bea@example.com")
    sign_in v
    assert_difference -> { Lead.count }, 1 do
      patch buyer_profile_path, params: { pre_approved: "yes", move_timeline_days: "30", budget: "600000" }
    end
    v.reload
    assert_equal "yes", v.pre_approved
    assert_equal 30, v.move_timeline_days
    assert_equal 60_000_000, v.budget_cents
    assert v.high_intent?
    assert_redirected_to edit_buyer_profile_path
  end

  test "update with just-browsing leaves low-intent and no handoff" do
    v = Visitor.create!(name: "Lou", email: "lou@example.com")
    sign_in v
    assert_no_difference -> { Lead.count } do
      patch buyer_profile_path, params: { pre_approved: "no", move_timeline_days: "", budget: "" }
    end
    refute v.reload.high_intent?
  end
end
