class Offer < ApplicationRecord
  SIDES = %w[seller buyer].freeze
  # drafting -> awaiting_broker (in the broker-sign queue) -> signed
  STATUSES = %w[drafting awaiting_broker signed].freeze

  belongs_to :lead
  belongs_to :property, optional: true
  has_many :negotiations, dependent: :destroy

  validates :side, presence: true, inclusion: { in: SIDES }
  validates :status, presence: true, inclusion: { in: STATUSES }
  validates :amount, numericality: { greater_than: 0 }, allow_nil: true

  # The broker-sign queue: offers a licensed human broker must review/sign.
  scope :awaiting_broker_sign, -> { where(status: "awaiting_broker").order(:created_at) }

  # Move a drafted offer into the awaiting-broker-sign queue.
  def enqueue_for_broker!
    update!(status: "awaiting_broker")
  end

  def sign!
    update!(status: "signed")
  end

  def awaiting_broker_sign?
    status == "awaiting_broker"
  end
end
