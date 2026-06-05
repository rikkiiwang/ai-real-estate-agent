require "test_helper"

class ConversationTest < ActiveSupport::TestCase
  test "messages from different channels belong to one ordered thread" do
    c = Conversation.create!(side: "buyer", contact: "a@example.com")
    c.messages.create!(channel: "chat", role: "visitor", body: "hi")
    c.messages.create!(channel: "sms", role: "visitor", body: "still me")
    c.messages.create!(channel: "voice", role: "visitor", body: "calling now")
    assert_equal %w[chat sms voice], c.messages.map(&:channel)
    assert_equal %w[chat sms voice], c.channels_used
  end

  test "merge_signals keeps existing values and ignores blanks" do
    c = Conversation.create!(side: "buyer", signals: { "preapproval" => "true" })
    c.merge_signals("move_timeline_days" => "20", "budget" => "", "preapproval" => nil)
    assert_equal "true", c.signals["preapproval"] # not overwritten by nil
    assert_equal "20", c.signals["move_timeline_days"]
    assert_not c.signals.key?("budget") # blank ignored
  end

  test "side is validated" do
    assert_not Conversation.new(side: "nope").valid?
  end
end
