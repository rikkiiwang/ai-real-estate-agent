require "test_helper"

class Buyer::ShowingsControllerTest < ActionDispatch::IntegrationTest
  SLOT = Time.utc(2099, 1, 5, 15, 0)

  def listing
    @listing ||= Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                                  list_price: 500_000, sqft: 2000, beds: 3, baths: 2)
  end

  test "requesting a showing creates a requested appointment and audits it" do
    assert_difference -> { Appointment.count }, 1 do
      assert_difference -> { AuditEvent.where(kind: "showing_requested").count }, 1 do
        post buyer_listing_showings_path(listing),
          params: { starts_at: SLOT.iso8601, kind: "tour", requester_name: "Pat", requester_email: "pat@example.com" }
      end
    end

    appt = Appointment.last
    assert_equal "requested", appt.status
    assert_equal "tour", appt.kind
    assert_equal listing.id, appt.property_id
    assert_equal SLOT, appt.starts_at
    assert_equal SLOT + 30.minutes, appt.ends_at
    assert_equal "pat@example.com", appt.requester_email
    assert_redirected_to buyer_listing_path(listing)
  end

  test "booking an already-taken slot is rejected with an alert" do
    Appointment.create!(property: listing, kind: "tour", status: "confirmed",
                        starts_at: SLOT, ends_at: SLOT + 30.minutes)

    assert_no_difference -> { Appointment.count } do
      post buyer_listing_showings_path(listing), params: { starts_at: SLOT.iso8601 }
    end
    assert_redirected_to buyer_listing_path(listing)
    assert_match(/just taken/, flash[:alert])
  end

  test "an overlapping (not identical) slot is also rejected" do
    Appointment.create!(property: listing, kind: "tour", status: "requested",
                        starts_at: SLOT, ends_at: SLOT + 30.minutes)
    overlapping = (SLOT + 15.minutes).iso8601

    assert_no_difference -> { Appointment.count } do
      post buyer_listing_showings_path(listing), params: { starts_at: overlapping }
    end
  end

  test "inspection kind is accepted, unknown kind falls back to tour" do
    post buyer_listing_showings_path(listing), params: { starts_at: SLOT.iso8601, kind: "inspection" }
    assert_equal "inspection", Appointment.last.kind

    post buyer_listing_showings_path(listing), params: { starts_at: (SLOT + 1.hour).iso8601, kind: "party" }
    assert_equal "tour", Appointment.last.kind
  end

  test "a missing time is rejected" do
    assert_no_difference -> { Appointment.count } do
      post buyer_listing_showings_path(listing), params: { starts_at: "" }
    end
    assert_match(/available time/, flash[:alert])
  end

  test "a malformed time string is rejected, not a 500" do
    # "99:99" makes BOTH Time.iso8601 and the Time.zone.parse fallback raise —
    # the double-raise that must not escape as a 500.
    assert_no_difference -> { Appointment.count } do
      post buyer_listing_showings_path(listing), params: { starts_at: "99:99" }
    end
    assert_redirected_to buyer_listing_path(listing)
    assert_match(/available time/, flash[:alert])
  end

  test "a non-browsable listing is not found" do
    retired = Property.create!(address: "9 Gone St", state: "listed", list_price: 500_000, retired_at: Time.current)
    post buyer_listing_showings_path(retired), params: { starts_at: SLOT.iso8601 }
    assert_response :not_found
  end
end
