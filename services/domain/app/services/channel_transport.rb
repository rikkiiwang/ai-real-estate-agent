# Outbound channel transport — the swappable seam for sending an agent reply out
# over a real communication channel (SMS / Email). It is the documented
# integration point: a real provider (Twilio, SendGrid) is one class away. Until
# credentials are present, delivery runs on the SIMULATED transport (synthetic,
# no network) so the demo shows the omnichannel behaviour honestly — every
# simulated send is labelled as such in the UI.
#
# Web channels (chat, voice) have no out-of-band transport — the reply renders in
# the browser — so deliver() returns nil for them.
require "net/http"
require "json"

module ChannelTransport
  Result = Struct.new(:status, :provider, :note, keyword_init: true)

  # --- Real provider entry points (plug a carrier in HERE) ----------------------
  # Each reports whether its credentials are configured; deliver() is the single
  # method to implement against the provider's SDK. They are intentionally not
  # wired — the seam is real, the integration is deferred.

  class TwilioSms
    def self.configured? = ENV["TWILIO_ACCOUNT_SID"].present? && ENV["TWILIO_AUTH_TOKEN"].present?

    # POST to the Twilio Messages API (form-encoded, basic auth). Only reached
    # when configured?; otherwise ChannelTransport.deliver uses Simulated.
    def deliver(to:, body:)
      sid = ENV["TWILIO_ACCOUNT_SID"]; token = ENV["TWILIO_AUTH_TOKEN"]; from = ENV["TWILIO_FROM"]
      ChannelTransport.http_post_form(
        URI("https://api.twilio.com/2010-04-01/Accounts/#{sid}/Messages.json"),
        { "From" => from.to_s, "To" => to.to_s, "Body" => body.to_s },
        basic_auth: [sid, token]
      )
      Result.new(status: "sent", provider: "twilio", note: "delivered via Twilio")
    rescue StandardError => e
      Result.new(status: "error", provider: "twilio", note: e.message)
    end
  end

  class SendgridEmail
    def self.configured? = ENV["SENDGRID_API_KEY"].present?

    # POST to the SendGrid v3 mail/send API (JSON, bearer auth). Only reached when
    # configured?; otherwise ChannelTransport.deliver uses Simulated.
    def deliver(to:, body:)
      payload = {
        personalizations: [{ to: [{ email: to.to_s }] }],
        from: { email: ENV["SENDGRID_FROM"].to_s }, subject: "Your Atlas update",
        content: [{ type: "text/plain", value: body.to_s }]
      }
      ChannelTransport.http_post_json(URI("https://api.sendgrid.com/v3/mail/send"), payload,
                                      bearer: ENV["SENDGRID_API_KEY"].to_s)
      Result.new(status: "sent", provider: "sendgrid", note: "delivered via SendGrid")
    rescue StandardError => e
      Result.new(status: "error", provider: "sendgrid", note: e.message)
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

  # Minimal HTTP posters (stubbed in tests). Only ever called when a provider is
  # configured, so the demo (no keys) never constructs them.
  def http_post_form(uri, fields, basic_auth: nil)
    req = Net::HTTP::Post.new(uri)
    req.set_form_data(fields)
    req.basic_auth(*basic_auth) if basic_auth
    _http_run(uri, req)
  end

  def http_post_json(uri, payload, bearer:)
    req = Net::HTTP::Post.new(uri)
    req["Authorization"] = "Bearer #{bearer}"
    req["Content-Type"] = "application/json"
    req.body = payload.to_json
    _http_run(uri, req)
  end

  def _http_run(uri, req)
    Net::HTTP.start(uri.host, uri.port, use_ssl: true, open_timeout: 5, read_timeout: 10) do |http|
      http.request(req)
    end
  end
end
