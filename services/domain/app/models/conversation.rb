class Conversation < ApplicationRecord
  SIDES = %w[buyer seller].freeze

  has_many :messages, dependent: :destroy

  validates :side, presence: true, inclusion: { in: SIDES }

  # The channels this conversation has actually been touched on, in first-seen
  # order — the proof that one thread spans multiple channels.
  def channels_used
    messages.order(:created_at).map(&:channel).uniq
  end

  # Merge newly-collected neutral fields, keeping existing values and ignoring
  # blanks. Stored as a plain hash on the conversation.
  def merge_signals(new_signals)
    merged = (signals || {}).dup
    (new_signals || {}).each do |k, v|
      next if v.nil? || v.to_s.strip.empty?

      merged[k.to_s] = v
    end
    self.signals = merged
  end

  def high_intent?
    intent.to_s.start_with?("high")
  end
end
