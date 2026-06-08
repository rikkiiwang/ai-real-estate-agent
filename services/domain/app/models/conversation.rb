# One durable conversation thread, keyed by a contact (email or phone). Every
# channel (chat/voice/sms/email) reads and writes the same thread, so the agent
# keeps context when a lead switches channels (R4). The brain's thread_id points
# here; this row is the durable record (brain memory is in-process).
class Conversation < ApplicationRecord
  has_many :messages, -> { order(:created_at) }, dependent: :destroy

  validates :contact, presence: true, uniqueness: { case_sensitive: false }
  normalizes :contact, with: ->(c) { Conversation.normalize_contact(c) }

  # Email → lowercased; a phone-shaped value → digits and '+' only; any other
  # identifier (e.g. a synthetic "voice-<id>") → kept, lowercased.
  def self.normalize_contact(raw)
    s = raw.to_s.strip
    return s.downcase if s.include?("@")
    return s.gsub(/[^\d+]/, "") if s.match?(/\A[\d\s+().\-]+\z/)

    s.downcase
  end

  def self.for(contact:, name: nil)
    convo = find_or_create_by!(contact: normalize_contact(contact))
    convo.update!(name: name) if name.present? && convo.name != name
    convo
  end

  def thread_id = "conv-#{id}"

  def append(channel:, role:, body:, ai_disclosed: false)
    msg = messages.create!(channel: channel.to_s, role: role.to_s, body: body.to_s, ai_disclosed: ai_disclosed)
    update_column(:last_channel, channel.to_s)
    msg
  end

  def transcript
    messages.map { |m| "[#{m.channel}] #{m.role}: #{m.body}" }.join("\n")
  end
end
