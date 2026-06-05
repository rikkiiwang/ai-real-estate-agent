require "test_helper"

class ChannelTransportTest < ActiveSupport::TestCase
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

  test "the real provider entry points report unconfigured and are not wired" do
    assert_not ChannelTransport::TwilioSms.configured?
    assert_not ChannelTransport::SendgridEmail.configured?
    assert_raises(NotImplementedError) { ChannelTransport::TwilioSms.new.deliver(to: "x", body: "y") }
    assert_raises(NotImplementedError) { ChannelTransport::SendgridEmail.new.deliver(to: "x", body: "y") }
  end
end
