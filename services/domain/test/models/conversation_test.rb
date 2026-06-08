require "test_helper"

class ConversationTest < ActiveSupport::TestCase
  test "find-or-create by normalized contact (email lowercased, phone digits)" do
    a = Conversation.for(contact: "Jordan@Example.com", name: "Jordan")
    b = Conversation.for(contact: "jordan@example.com")
    assert_equal a.id, b.id
    p1 = Conversation.for(contact: "+1 (512) 555-0100")
    p2 = Conversation.for(contact: "+15125550100")
    assert_equal p1.id, p2.id
  end

  test "append records a channel-tagged message and updates last_channel" do
    c = Conversation.for(contact: "j@x.com")
    c.append(channel: "chat", role: "user", body: "hi")
    c.append(channel: "sms", role: "agent", body: "hello", ai_disclosed: false)
    assert_equal %w[chat sms], c.messages.map(&:channel)
    assert_equal "sms", c.reload.last_channel
  end

  test "thread_id and transcript" do
    c = Conversation.for(contact: "j@x.com")
    c.append(channel: "chat", role: "user", body: "what's it worth?")
    c.append(channel: "voice", role: "agent", body: "About $610k.")
    assert_equal "conv-#{c.id}", c.thread_id
    assert_equal "[chat] user: what's it worth?\n[voice] agent: About $610k.", c.transcript
  end

  test "message rejects an unknown channel or role" do
    c = Conversation.for(contact: "j@x.com")
    assert_not c.messages.build(channel: "fax", role: "user", body: "x").valid?
    assert_not c.messages.build(channel: "chat", role: "robot", body: "x").valid?
  end
end
