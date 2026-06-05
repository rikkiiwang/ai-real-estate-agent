# Outbound channel transport — the swappable seam for sending an agent reply out
# over a real communication channel (SMS / Email). It is the documented
# integration point: a real provider (Twilio, SendGrid) is one class away. Until
# credentials are present, delivery runs on the SIMULATED transport (synthetic,
# no network) so the demo shows the omnichannel behaviour honestly — every
# simulated send is labelled as such in the UI.
#
# Web channels (chat, voice) have no out-of-band transport — the reply renders in
# the browser — so deliver() returns nil for them.
module ChannelTransport
  Result = Struct.new(:status, :provider, :note, keyword_init: true)

  # --- Real provider entry points (plug a carrier in HERE) ----------------------
  # Each reports whether its credentials are configured; deliver() is the single
  # method to implement against the provider's SDK. They are intentionally not
  # wired — the seam is real, the integration is deferred.

  class TwilioSms
    def self.configured? = ENV["TWILIO_ACCOUNT_SID"].present? && ENV["TWILIO_AUTH_TOKEN"].present?

    # Implement with twilio-ruby: client.messages.create(from:, to:, body:).
    def deliver(to:, body:)
      raise NotImplementedError, "Wire Twilio SMS here (twilio-ruby Messages.create) — and add an inbound webhook"
    end
  end

  class SendgridEmail
    def self.configured? = ENV["SENDGRID_API_KEY"].present?

    # Implement with ActionMailer/SendGrid send; pair with an Inbound Parse webhook.
    def deliver(to:, body:)
      raise NotImplementedError, "Wire SendGrid email here (Mail send) — and add an Inbound Parse webhook"
    end
  end

  # --- Simulated transport (synthetic; powers the demo) -------------------------
  class Simulated
    def initialize(channel) = @channel = channel.to_s

    def deliver(to:, body:)
      Rails.logger.info("[transport:simulated] #{@channel} -> #{to}: #{body.to_s[0, 80]}")
      Result.new(status: "simulated", provider: "simulated",
                 note: "no live carrier — connect a provider to go live")
    end
  end

  # Channels that travel out-of-band (a real carrier would deliver these).
  REAL = { "sms" => TwilioSms, "email" => SendgridEmail }.freeze

  module_function

  # Send an agent reply out over the channel. Returns a Result for SMS/Email
  # (real if the provider is configured, else simulated), or nil for web
  # channels (chat/voice) whose reply just renders in the browser.
  def deliver(channel:, to:, body:)
    klass = REAL[channel.to_s]
    return nil unless klass

    klass.configured? ? klass.new.deliver(to: to, body: body) : Simulated.new(channel).deliver(to: to, body: body)
  end

  # Whether a channel is delivered out-of-band (vs. rendered in the browser).
  def out_of_band?(channel)
    REAL.key?(channel.to_s)
  end
end
