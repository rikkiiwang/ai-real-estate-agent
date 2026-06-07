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
end
