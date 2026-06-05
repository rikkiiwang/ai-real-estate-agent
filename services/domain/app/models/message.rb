class Message < ApplicationRecord
  ROLES = %w[visitor agent].freeze

  belongs_to :conversation

  validates :channel, presence: true, inclusion: { in: Channel::CHANNELS }
  validates :role, presence: true, inclusion: { in: ROLES }

  default_scope { order(:created_at) }
end
