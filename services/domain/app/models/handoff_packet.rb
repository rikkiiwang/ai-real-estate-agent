class HandoffPacket < ApplicationRecord
  STATUSES = %w[pending claimed resolved].freeze

  belongs_to :lead

  validates :trigger, presence: true
  validates :status, presence: true, inclusion: { in: STATUSES }
  validates :confidence, numericality: { in: 0.0..1.0 }, allow_nil: true

  # The broker handoff queue: packets awaiting a human, newest first.
  scope :queue, -> { where(status: "pending").order(created_at: :desc) }
end
