require "test_helper"

class Broker::AppointmentsControllerTest < ActionDispatch::IntegrationTest
  def setup
    @prop = Property.create!(address: "1 Oak St", state: "listed", list_price: 500_000)
    @appt = Appointment.create!(property: @prop, kind: "tour", status: "requested",
                                starts_at: Time.utc(2099, 1, 5, 15, 0),
                                ends_at: Time.utc(2099, 1, 5, 15, 30),
                                requester_email: "pat@example.com")
  end

  def sign_in_broker
    post session_path, params: { name: "Bea Broker", email: "broker@atlas.example" } # allowlisted
  end

  test "a non-broker cannot confirm or decline" do
    post session_path, params: { name: "Casey", email: "casey@example.com" }
    post confirm_broker_appointment_path(@appt)
    assert_redirected_to root_path
    assert_equal "requested", @appt.reload.status
  end

  test "broker confirms a requested showing and it is audited" do
    sign_in_broker
    assert_difference -> { AuditEvent.where(kind: "showing_confirmed").count }, 1 do
      post confirm_broker_appointment_path(@appt)
    end
    assert_redirected_to broker_dashboard_path
    @appt.reload
    assert_equal "confirmed", @appt.status
    assert_equal "broker@atlas.example", @appt.broker_email
    assert @appt.confirmed_at.present?
  end

  test "confirm is refused when the broker is already booked elsewhere" do
    sign_in_broker
    other = Property.create!(address: "9 Elm St", state: "listed", list_price: 600_000)
    Appointment.create!(property: other, kind: "tour", status: "confirmed",
                        broker_email: "broker@atlas.example",
                        starts_at: @appt.starts_at, ends_at: @appt.ends_at)

    assert_no_difference -> { AuditEvent.where(kind: "showing_confirmed").count } do
      post confirm_broker_appointment_path(@appt)
    end
    assert_equal "requested", @appt.reload.status
    assert_equal "blocked", AuditEvent.where(kind: "showing_conflict").last.decision
    assert_match(/conflicts/, flash[:alert])
  end

  test "broker declines a requested showing" do
    sign_in_broker
    assert_difference -> { AuditEvent.where(kind: "showing_declined").count }, 1 do
      post decline_broker_appointment_path(@appt)
    end
    @appt.reload
    assert_equal "declined", @appt.status
    assert @appt.declined_at.present?
  end

  test "a declined showing frees its slot for a new request" do
    sign_in_broker
    post decline_broker_appointment_path(@appt)
    # the slot is now free again
    assert ShowingScheduler.slot_free?(property: @prop, starts_at: @appt.starts_at, ends_at: @appt.ends_at)
  end

  test "completing a linked inspection auto-records inspection_cleared (R10)" do
    sign_in_broker
    prop = Property.create!(address: "9 Insp St", state: "listed", list_price: 500_000)
    lead = Lead.create!(side: "buyer", address: "9 Insp St", contact: "b@x.com", intent: "high")
    offer = Offer.create!(lead: lead, side: "buyer", status: "signed", property: prop)
    appt = Appointment.create!(property: prop, kind: "inspection", status: "confirmed", offer: offer,
                               starts_at: Time.utc(2099, 2, 2, 15, 0), ends_at: Time.utc(2099, 2, 2, 15, 30),
                               broker_email: "broker@atlas.example")
    assert_difference -> { ClosingMilestone.count }, 1 do
      post complete_broker_appointment_path(appt)
    end
    assert_equal "completed", appt.reload.status
    assert_equal "inspection_cleared", offer.closing_milestones.first.milestone
  end

  test "completing a tour records no closing milestone" do
    sign_in_broker
    prop = Property.create!(address: "9 Tour St", state: "listed", list_price: 500_000)
    appt = Appointment.create!(property: prop, kind: "tour", status: "confirmed",
                               starts_at: Time.utc(2099, 2, 3, 15, 0), ends_at: Time.utc(2099, 2, 3, 15, 30))
    assert_no_difference -> { ClosingMilestone.count } do
      post complete_broker_appointment_path(appt)
    end
    assert_equal "completed", appt.reload.status
  end
end
