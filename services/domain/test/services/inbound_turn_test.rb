require "test_helper"

class InboundTurnTest < ActiveSupport::TestCase
  class OkBrain
    def orchestrate(**) = Struct.new(:message).new("Happy to help — here's a quick answer.")
  end
  class DeadBrain
    def orchestrate(**) = raise("brain down")
  end

  test "appends the inbound turn, orchestrates, appends the reply" do
    r = InboundTurn.call(contact: "+15125550100", channel: "sms", body: "is 9 Demo St a deal?", client: OkBrain.new)
    assert_equal "Happy to help — here's a quick answer.", r.reply
    assert_equal %w[user agent], r.conversation.messages.map(&:role)
    assert_equal %w[sms sms], r.conversation.messages.map(&:channel)
  end

  test "brain-down still appends a fallback reply" do
    r = InboundTurn.call(contact: "buyer@x.com", channel: "email", body: "hi", client: DeadBrain.new)
    assert_match(/broker/i, r.reply)
    assert_equal 2, r.conversation.messages.count
  end
end
