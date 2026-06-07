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

  validates :kind, inclusion: { in: KINDS }
  validates :status, inclusion: { in: STATUSES }
  validates :starts_at, :ends_at, presence: true
  validate :ends_after_starts

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

  private

  def ends_after_starts
    return if starts_at.blank? || ends_at.blank?

    errors.add(:ends_at, "must be after starts_at") if ends_at <= starts_at
  end
end
