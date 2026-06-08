require "test_helper"

class ChannelTransportTest < ActiveSupport::TestCase
  # Temporarily replace a ChannelTransport module method with a capturing stub,
  # so adapter tests assert the request without making a live HTTP call.
  def with_capture(name)
    original = ChannelTransport.method(name)
    captured = {}
    ChannelTransport.define_singleton_method(name) do |*args, **kw|
      captured[:args] = args
      captured[:kw] = kw
      "OK"
    end
    yield captured
  ensure
    ChannelTransport.singleton_class.define_method(name, original)
  end
  test "SMS/Email are out-of-band; chat/voice render in the browser" do
    assert ChannelTransport.out_of_band?("sms")
    assert ChannelTransport.out_of_band?("email")
    assert_not ChannelTransport.out_of_band?("chat")
    assert_not ChannelTransport.out_of_band?("voice")
  end

  test "delivering on a web channel is a no-op (nil)" do
    assert_nil ChannelTransport.deliver(channel: "chat", to: "x@y.com", body: "hi")
    assert_nil ChannelTransport.deliver(channel: "voice", to: "x@y.com", body: "hi")
  end

  test "SMS/Email fall back to the simulated transport when no provider is configured" do
    sms = ChannelTransport.deliver(channel: "sms", to: "+15125550000", body: "hi")
    assert_equal "simulated", sms.status
    assert_match(/no live carrier/i, sms.note)

    email = ChannelTransport.deliver(channel: "email", to: "x@y.com", body: "hi")
    assert_equal "simulated", email.status
  end

  test "the real providers report unconfigured by default (demo stays simulated)" do
    assert_not ChannelTransport::TwilioSms.configured?
    assert_not ChannelTransport::SendgridEmail.configured?
    # Unconfigured, deliver() routes to the simulated transport — never a live call.
    assert_equal "simulated", ChannelTransport.deliver(channel: "sms", to: "+1", body: "y").status
    assert_equal "simulated", ChannelTransport.deliver(channel: "email", to: "x@y.com", body: "y").status
  end

  test "TwilioSms posts to the Messages API when configured (no live HTTP in test)" do
    ENV["TWILIO_ACCOUNT_SID"] = "AC123"; ENV["TWILIO_AUTH_TOKEN"] = "tok"; ENV["TWILIO_FROM"] = "+15120000000"
    with_capture(:http_post_form) do |cap|
      r = ChannelTransport::TwilioSms.new.deliver(to: "+15125550100", body: "hi there")
      assert_equal "sent", r.status
      assert_equal "twilio", r.provider
      uri, fields = cap[:args]
      assert_match %r{Accounts/AC123/Messages\.json}, uri.to_s
      assert_equal "hi there", fields["Body"]
      assert_equal "+15125550100", fields["To"]
    end
  ensure
    %w[TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_FROM].each { |k| ENV.delete(k) }
  end

  test "SendgridEmail posts to the v3 send API when configured" do
    ENV["SENDGRID_API_KEY"] = "SG.x"; ENV["SENDGRID_FROM"] = "atlas@example.com"
    with_capture(:http_post_json) do |cap|
      r = ChannelTransport::SendgridEmail.new.deliver(to: "buyer@example.com", body: "your update")
      assert_equal "sent", r.status
      uri, payload = cap[:args]
      assert_match %r{/v3/mail/send}, uri.to_s
      assert_equal "buyer@example.com", payload[:personalizations][0][:to][0][:email]
    end
  ensure
    %w[SENDGRID_API_KEY SENDGRID_FROM].each { |k| ENV.delete(k) }
  end
end
