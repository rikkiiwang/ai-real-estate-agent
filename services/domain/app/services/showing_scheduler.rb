# The real "dynamic" core of R6: a deterministic, DB-only collision-avoidance
# engine. It generates business-hours candidate slots over a horizon, then
# subtracts the past, property double-bookings, broker double-bookings, and
# blacked-out (under-offer / sold / retired) properties — so the slots it offers
# are genuinely free. No external calendar, no network calls.
#
# Determinism: every entry point takes `now` explicitly and never reads the wall
# clock internally, so a given (data, now) always yields the same slots.
class ShowingScheduler
  SLOT_MINUTES   = 30
  HORIZON_DAYS   = 7
  DAY_START_HOUR = 9   # 09:00, inclusive
  DAY_END_HOUR   = 18  # 18:00, exclusive (last slot ends by 18:00)
  MAX_SLOTS      = 12

  Slot = Struct.new(:starts_at, :ends_at, keyword_init: true)
  Result = Struct.new(:slots, :reason, keyword_init: true) do
    def any? = slots.any?
  end

  # Free slots for `property` as of `now`. When `broker_email` is given, a slot
  # is also dropped if that broker is busy elsewhere then. Returns a Result whose
  # `reason` explains an empty list (blackout or no openings).
  def self.available_slots(property:, now:, broker_email: nil, kind: "tour")
    blackout = blackout_reason(property)
    return Result.new(slots: [], reason: blackout) if blackout

    property_busy = Appointment.active.for_property(property).to_a
    broker_busy   = broker_email.present? ? Appointment.active.for_broker(broker_email).to_a : []

    slots = []
    candidate_slots(now).each do |slot|
      next if collides?(property_busy, slot) || collides?(broker_busy, slot)

      slots << slot
      break if slots.size >= MAX_SLOTS
    end

    reason = slots.empty? ? "No openings in the next #{HORIZON_DAYS} days" : nil
    Result.new(slots: slots, reason: reason)
  end

  # Commit-time re-check used by booking and broker-confirm: true iff the exact
  # [starts_at, ends_at) slot has no ACTIVE overlap on the property (or broker).
  # `excluding` skips a given appointment id (so confirming doesn't conflict with
  # itself).
  def self.slot_free?(property:, starts_at:, ends_at:, broker_email: nil, excluding: nil)
    return false if starts_at.blank? || ends_at.blank? || ends_at <= starts_at

    property_scope = Appointment.active.for_property(property)
    property_scope = property_scope.where.not(id: excluding) if excluding
    return false if property_scope.any? { |a| a.overlaps?(starts_at, ends_at) }

    if broker_email.present?
      broker_scope = Appointment.active.for_broker(broker_email)
      broker_scope = broker_scope.where.not(id: excluding) if excluding
      return false if broker_scope.any? { |a| a.overlaps?(starts_at, ends_at) }
    end

    true
  end

  # Honest blackout reason, or nil when the property is showable.
  def self.blackout_reason(property)
    return "Not available for showings (retired listing)" if property.retired_at.present?
    return "Not available for showings (#{property.state})" if %w[under_offer sold].include?(property.state)

    nil
  end

  # Deterministic business-hours candidate slots over [now, now + HORIZON_DAYS),
  # excluding any slot that starts at or before `now`.
  def self.candidate_slots(now)
    midnight = now.beginning_of_day
    slots = []
    (0...HORIZON_DAYS).each do |day|
      day_base  = midnight + day.days
      day_open  = day_base + DAY_START_HOUR.hours
      day_close = day_base + DAY_END_HOUR.hours
      cursor = day_open
      while cursor + SLOT_MINUTES.minutes <= day_close
        slot_start = cursor
        cursor += SLOT_MINUTES.minutes
        next if slot_start <= now # no past or already-started slots

        slots << Slot.new(starts_at: slot_start, ends_at: slot_start + SLOT_MINUTES.minutes)
      end
    end
    slots
  end

  def self.collides?(appointments, slot)
    appointments.any? { |a| a.overlaps?(slot.starts_at, slot.ends_at) }
  end

  private_class_method :candidate_slots, :collides?
end
