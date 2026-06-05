require "test_helper"

class ChannelTest < ActiveSupport::TestCase
  test "supports voice, sms, email, chat" do
    assert_equal %w[voice sms email chat], Channel::CHANNELS
    assert Channel.valid?("email")
    assert_not Channel.valid?("fax")
  end

  test "voice hard-requires AI disclosure; text channels are voluntary" do
    assert Channel.mandatory_disclosure?("voice")
    assert_not Channel.mandatory_disclosure?("sms")
    assert_not Channel.mandatory_disclosure?("email")
    assert_not Channel.mandatory_disclosure?("chat")
  end

  test "disclosure copy differs for voice vs text and email is a text channel" do
    assert_match(/speaking with AI/i, Channel.disclosure_text("voice"))
    assert_equal Channel::TEXT_DISCLOSURE, Channel.disclosure_text("email")
    assert Channel.text?("email")
    assert_not Channel.text?("voice")
  end
end
