class Lead < ApplicationRecord
  SIDES = %w[seller buyer].freeze
  INTENTS = %w[high low unknown].freeze

  has_many :offers, dependent: :destroy
  has_many :handoff_packets, dependent: :destroy

  validates :side, presence: true, inclusion: { in: SIDES }
  validates :address, presence: true
  validates :intent, presence: true, inclusion: { in: INTENTS }
end
