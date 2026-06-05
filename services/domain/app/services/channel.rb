# The outreach channels the Concierge supports and their AI-disclosure rules.
# Ports services/voice/disclosure.go to the Rails side and adds email as a text
# channel. Disclosure differs by channel: an automated VOICE call must disclose
# AI before a substantive turn; text channels (chat/sms/email) are voluntary
# (fail-safe toward more disclosure). Transport itself is simulated here — this
# layer only owns the channel set and the disclosure copy.
module Channel
  CHANNELS = %w[voice sms email chat].freeze

  VOICE_DISCLOSURE = "This is an automated assistant from Atlas — you're speaking with AI. " \
                     "I can bring in a licensed human broker at any time.".freeze
  TEXT_DISCLOSURE = "Heads up: replies here may come from Atlas's automated assistant. " \
                    "Ask anytime for a licensed human broker.".freeze

  module_function

  def valid?(channel)
    CHANNELS.include?(channel.to_s)
  end

  # Voice hard-requires AI disclosure; text channels are voluntary.
  def mandatory_disclosure?(channel)
    channel.to_s == "voice"
  end

  def disclosure_text(channel)
    channel.to_s == "voice" ? VOICE_DISCLOSURE : TEXT_DISCLOSURE
  end

  # A text channel is anything that isn't the voice call.
  def text?(channel)
    valid?(channel) && channel.to_s != "voice"
  end
end
