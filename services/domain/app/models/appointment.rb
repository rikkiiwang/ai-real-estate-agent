# A requested or scheduled property showing/inspection (R6 dynamic scheduling).
#
# An ACTIVE appointment (requested or confirmed) occupies a half-open
# [starts_at, ends_at) slot on its property — and, when a broker is assigned, on
# that broker. ShowingScheduler subtracts these from generated availability so
# two showings never double-book the same property or broker.
#
# Intervals are half-open: a slot ending exactly when another begins does NOT
# overlap (back-to-back showings are fine).
class Appointment < ApplicationRecord
  KINDS = %w[tour inspection].freeze
  STATUSES = %w[requested confirmed declined cancelled completed].freeze
  ACTIVE_STATUSES = %w[requested confirmed].freeze

  belongs_to :property
  belongs_to :lead, optional: true
  belongs_to :offer, optional: true

  validates :kind, inclusion: { in: KINDS }
  validates :status, inclusion: { in: STATUSES }
  validates :starts_at, :ends_at, presence: true
  validate :ends_after_starts
  # Race guard: two active (requested/confirmed) showings can't both occupy an
  # overlapping slot on the same property (or the same broker). The booking and
  # broker-confirm paths re-check ShowingScheduler.slot_free? before writing; this
  # is the model-level backstop so a concurrent double-book is rejected at save.
  validate :no_active_double_booking, on: :create

  # Active = still occupies a slot. Declined/cancelled/completed free it.
  scope :active, -> { where(status: ACTIVE_STATUSES) }
  scope :pending, -> { where(status: "requested").order(:starts_at) }
  scope :for_property, ->(property) { where(property: property) }
  scope :for_broker, ->(email) { email.present? ? where(broker_email: email) : none }

  # Half-open overlap: true iff this appointment's interval intersects
  # [other_start, other_end). Touching endpoints do not overlap.
  def overlaps?(other_start, other_end)
    starts_at < other_end && ends_at > other_start
  end

  # The signed deal this (inspection) appointment belongs to: an explicit offer,
  # else the lone signed offer on this property — disambiguated by the requester's
  # email when there is more than one. nil when nothing resolves.
  def resolve_offer
    return offer if offer

    scope = Offer.where(property_id: property_id, status: "signed")
    by_email = scope.joins(:lead).where(leads: { contact: requester_email })
    by_email.first || (scope.count == 1 ? scope.first : nil)
  end

  private

  def ends_after_starts
    return if starts_at.blank? || ends_at.blank?

    errors.add(:ends_at, "must be after starts_at") if ends_at <= starts_at
  end

  def no_active_double_booking
    return unless ACTIVE_STATUSES.include?(status)
    return if starts_at.blank? || ends_at.blank? || property.blank?

    if Appointment.active.for_property(property).any? { |a| a.overlaps?(starts_at, ends_at) }
      errors.add(:base, "overlaps an existing showing for this property")
      return
    end

    return if broker_email.blank?
    if Appointment.active.for_broker(broker_email).any? { |a| a.overlaps?(starts_at, ends_at) }
      errors.add(:base, "overlaps another showing for this broker")
    end
  end
end
