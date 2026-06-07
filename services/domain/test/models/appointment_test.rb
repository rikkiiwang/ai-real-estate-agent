require "test_helper"

class AppointmentTest < ActiveSupport::TestCase
  def property
    @property ||= Property.create!(address: "1 Oak St", state: "listed",
                                   region: "Austin 78704", list_price: 500_000,
                                   sqft: 2000, beds: 3, baths: 2)
  end

  def appt(attrs = {})
    Appointment.new({
      property: property, kind: "tour", status: "requested",
      starts_at: Time.utc(2026, 6, 8, 10, 0), ends_at: Time.utc(2026, 6, 8, 10, 30)
    }.merge(attrs))
  end

  test "valid with required fields" do
    assert appt.valid?
  end

  test "rejects unknown kind and status" do
    refute appt(kind: "party").valid?
    refute appt(status: "bogus").valid?
  end

  test "requires starts_at and ends_at" do
    refute appt(starts_at: nil).valid?
    refute appt(ends_at: nil).valid?
  end

  test "ends_at must be after starts_at" do
    refute appt(ends_at: Time.utc(2026, 6, 8, 10, 0)).valid?  # equal
    refute appt(ends_at: Time.utc(2026, 6, 8, 9, 30)).valid?  # before
    assert appt(ends_at: Time.utc(2026, 6, 8, 11, 0)).valid?  # after
  end

  test "lead is optional" do
    assert appt(lead: nil).valid?
  end

  test "active scope is requested + confirmed only" do
    a = appt.tap(&:save!)
    b = appt(status: "confirmed", starts_at: Time.utc(2026, 6, 9, 10, 0), ends_at: Time.utc(2026, 6, 9, 10, 30)).tap(&:save!)
    appt(status: "declined", starts_at: Time.utc(2026, 6, 10, 10, 0), ends_at: Time.utc(2026, 6, 10, 10, 30)).save!
    appt(status: "cancelled", starts_at: Time.utc(2026, 6, 11, 10, 0), ends_at: Time.utc(2026, 6, 11, 10, 30)).save!

    assert_equal [a.id, b.id].sort, Appointment.active.pluck(:id).sort
  end

  test "pending scope is requested ordered by starts_at" do
    late = appt(starts_at: Time.utc(2026, 6, 9, 10, 0), ends_at: Time.utc(2026, 6, 9, 10, 30)).tap(&:save!)
    early = appt(starts_at: Time.utc(2026, 6, 8, 10, 0), ends_at: Time.utc(2026, 6, 8, 10, 30)).tap(&:save!)
    appt(status: "confirmed", starts_at: Time.utc(2026, 6, 7, 10, 0), ends_at: Time.utc(2026, 6, 7, 10, 30)).save!

    assert_equal [early.id, late.id], Appointment.pending.pluck(:id)
  end

  test "for_broker scopes by email and returns none for blank" do
    mine = appt(broker_email: "b@example.com").tap(&:save!)
    appt(broker_email: "other@example.com", starts_at: Time.utc(2026, 6, 9, 10, 0), ends_at: Time.utc(2026, 6, 9, 10, 30)).save!

    assert_equal [mine.id], Appointment.for_broker("b@example.com").pluck(:id)
    assert_empty Appointment.for_broker(nil)
  end

  test "overlaps? uses half-open intervals (touching does not overlap)" do
    a = appt(starts_at: Time.utc(2026, 6, 8, 10, 0), ends_at: Time.utc(2026, 6, 8, 10, 30))
    # overlapping
    assert a.overlaps?(Time.utc(2026, 6, 8, 10, 15), Time.utc(2026, 6, 8, 10, 45))
    assert a.overlaps?(Time.utc(2026, 6, 8, 9, 45), Time.utc(2026, 6, 8, 10, 15))
    # touching at the end / start -> NOT overlapping
    refute a.overlaps?(Time.utc(2026, 6, 8, 10, 30), Time.utc(2026, 6, 8, 11, 0))
    refute a.overlaps?(Time.utc(2026, 6, 8, 9, 30), Time.utc(2026, 6, 8, 10, 0))
    # disjoint
    refute a.overlaps?(Time.utc(2026, 6, 8, 12, 0), Time.utc(2026, 6, 8, 12, 30))
  end
end
