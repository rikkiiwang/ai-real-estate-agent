# One turn in a Conversation, tagged with the channel it arrived/left on and the
# role (user/agent/broker). ai_disclosed records whether AI disclosure was made
# on this turn (voice mandates it).
class Message < ApplicationRecord
  CHANNELS = Channel::CHANNELS
  ROLES = %w[user agent broker].freeze

  belongs_to :conversation

  validates :channel, inclusion: { in: CHANNELS }
  validates :role, inclusion: { in: ROLES }
end
