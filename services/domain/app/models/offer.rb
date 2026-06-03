class Offer < ApplicationRecord
  SIDES = %w[seller buyer].freeze
  # drafting -> awaiting_broker (in the broker-sign queue) -> signed
  STATUSES = %w[drafting awaiting_broker signed].freeze

  belongs_to :lead
  belongs_to :property, optional: true
  has_many :negotiations, dependent: :destroy
  has_one :offer_metric, dependent: :destroy
  has_one :contract, dependent: :destroy

  validates :side, presence: true, inclusion: { in: SIDES }
  validates :status, presence: true, inclusion: { in: STATUSES }
  validates :amount, numericality: { greater_than: 0 }, allow_nil: true

  # The broker-sign queue: offers a licensed human broker must review/sign.
  scope :awaiting_broker_sign, -> { where(status: "awaiting_broker").order(:created_at) }

  # Move a drafted offer into the awaiting-broker-sign queue. This is the
  # canonical "offer drafted" moment, so it is where time-to-offer is stamped.
  def enqueue_for_broker!
    transaction do
      update!(status: "awaiting_broker")
      OfferMetric.record_for(self)
    end
  end

  def sign!
    update!(status: "signed")
  end

  def awaiting_broker_sign?
    status == "awaiting_broker"
  end
end
