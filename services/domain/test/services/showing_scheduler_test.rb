require "test_helper"

class ShowingSchedulerTest < ActiveSupport::TestCase
  # A fixed reference time: Mon 2026-06-08 08:00 UTC, before business hours.
  NOW = Time.utc(2026, 6, 8, 8, 0)

  def property(attrs = {})
    Property.create!({ address: "1 Oak St", state: "listed", region: "Austin 78704",
                       list_price: 500_000, sqft: 2000, beds: 3, baths: 2 }.merge(attrs))
  end

  def book!(prop, start_h, start_m, end_h, end_m, day: 8, status: "confirmed", broker: nil)
    Appointment.create!(property: prop, kind: "tour", status: status,
                        starts_at: Time.utc(2026, 6, day, start_h, start_m),
                        ends_at: Time.utc(2026, 6, day, end_h, end_m),
                        broker_email: broker)
  end

  test "generates 30-minute business-hours slots, none at/before now" do
    result = ShowingScheduler.available_slots(property: property, now: NOW)

    assert result.any?
    assert_nil result.reason
    assert_equal ShowingScheduler::MAX_SLOTS, result.slots.size
    assert_equal Time.utc(2026, 6, 8, 9, 0), result.slots.first.starts_at
    result.slots.each do |s|
      assert s.starts_at > NOW
      assert_equal 30 * 60, (s.ends_at - s.starts_at).to_i
      assert s.starts_at.hour >= ShowingScheduler::DAY_START_HOUR
      assert s.ends_at.hour <= ShowingScheduler::DAY_END_HOUR
    end
  end

  test "excludes slots at or before now" do
    result = ShowingScheduler.available_slots(property: property, now: Time.utc(2026, 6, 8, 10, 15))
    assert_equal Time.utc(2026, 6, 8, 10, 30), result.slots.first.starts_at
    assert(result.slots.none? { |s| s.starts_at <= Time.utc(2026, 6, 8, 10, 15) })
  end

  test "a confirmed appointment removes the overlapping property slot" do
    prop = property
    book!(prop, 10, 0, 10, 30)
    result = ShowingScheduler.available_slots(property: prop, now: NOW)
    assert(result.slots.none? { |s| s.starts_at == Time.utc(2026, 6, 8, 10, 0) })
    # neighbours remain
    assert(result.slots.any? { |s| s.starts_at == Time.utc(2026, 6, 8, 9, 30) })
    assert(result.slots.any? { |s| s.starts_at == Time.utc(2026, 6, 8, 10, 30) })
  end

  test "a busy broker elsewhere removes that slot when broker scoped" do
    other = property(address: "9 Elm St")
    book!(other, 11, 0, 11, 30, broker: "b@example.com")
    subject = property(address: "1 Oak St")

    result = ShowingScheduler.available_slots(property: subject, now: NOW, broker_email: "b@example.com")
    assert(result.slots.none? { |s| s.starts_at == Time.utc(2026, 6, 8, 11, 0) })

    # Without the broker scope, the subject property itself is free at 11:00.
    unscoped = ShowingScheduler.available_slots(property: subject, now: NOW)
    assert(unscoped.slots.any? { |s| s.starts_at == Time.utc(2026, 6, 8, 11, 0) })
  end

  test "blacked-out properties yield no slots with an honest reason" do
    under_offer = property(address: "2 Oak St", state: "under_offer")
    sold = property(address: "3 Oak St", state: "sold")
    retired = property(address: "4 Oak St", retired_at: Time.utc(2026, 6, 1))

    r1 = ShowingScheduler.available_slots(property: under_offer, now: NOW)
    assert_empty r1.slots
    assert_match(/under_offer/, r1.reason)

    r2 = ShowingScheduler.available_slots(property: sold, now: NOW)
    assert_empty r2.slots
    assert_match(/sold/, r2.reason)

    r3 = ShowingScheduler.available_slots(property: retired, now: NOW)
    assert_empty r3.slots
    assert_match(/retired/, r3.reason)
  end

  test "a fully-booked horizon reports no openings" do
    prop = property
    # One block spanning the entire 7-day horizon overlaps every candidate slot.
    Appointment.create!(property: prop, kind: "tour", status: "confirmed",
                        starts_at: Time.utc(2026, 6, 8, 9, 0),
                        ends_at: Time.utc(2026, 6, 14, 18, 0))
    result = ShowingScheduler.available_slots(property: prop, now: NOW)
    assert_empty result.slots
    assert_equal "No openings in the next 7 days", result.reason
  end

  test "slot_free? reflects active overlaps and honors excluding" do
    prop = property
    appt = book!(prop, 10, 0, 10, 30)

    refute ShowingScheduler.slot_free?(property: prop, starts_at: Time.utc(2026, 6, 8, 10, 0), ends_at: Time.utc(2026, 6, 8, 10, 30))
    # touching slot is free (half-open)
    assert ShowingScheduler.slot_free?(property: prop, starts_at: Time.utc(2026, 6, 8, 10, 30), ends_at: Time.utc(2026, 6, 8, 11, 0))
    # excluding the appointment itself frees its own slot (used on confirm)
    assert ShowingScheduler.slot_free?(property: prop, starts_at: Time.utc(2026, 6, 8, 10, 0), ends_at: Time.utc(2026, 6, 8, 10, 30), excluding: appt.id)
  end

  test "a declined appointment does not block its slot" do
    prop = property
    book!(prop, 10, 0, 10, 30, status: "declined")
    result = ShowingScheduler.available_slots(property: prop, now: NOW)
    assert(result.slots.any? { |s| s.starts_at == Time.utc(2026, 6, 8, 10, 0) })
  end

  test "deterministic: same inputs yield identical slots" do
    prop = property
    a = ShowingScheduler.available_slots(property: prop, now: NOW).slots.map(&:starts_at)
    b = ShowingScheduler.available_slots(property: prop, now: NOW).slots.map(&:starts_at)
    assert_equal a, b
  end
end
