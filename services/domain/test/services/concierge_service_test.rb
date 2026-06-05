require "test_helper"

class ConciergeServiceTest < ActiveSupport::TestCase
  def convo(side: "buyer")
    Conversation.create!(side: side, contact: "buyer@example.com")
  end

  test "appending on a second channel preserves the prior thread and signals" do
    c = convo
    ConciergeService.ingest(conversation: c, channel: "chat", body: "looking around")
    ConciergeService.ingest(conversation: c, channel: "email", body: "more info?", signals: { "budget" => "700000" })
    c.reload
    assert_equal %w[chat email], c.messages.map(&:channel)
    assert_equal "700000", c.signals["budget"]
  end

  test "becoming high-intent routes exactly one packet into the broker queue" do
    c = convo
    assert_difference "HandoffPacket.queue.count", 1 do
      r = ConciergeService.ingest(conversation: c, channel: "sms", body: "ready",
                                  signals: { "preapproval" => "true", "move_timeline_days" => "20" })
      assert r.handed_off
    end
    packet = HandoffPacket.queue.first
    assert_equal "high_intent", packet.trigger
    assert_equal "high", packet.lead.intent
  end

  test "a looky-loo creates no handoff" do
    c = convo
    assert_no_difference "HandoffPacket.count" do
      r = ConciergeService.ingest(conversation: c, channel: "chat", body: "just curious")
      assert_not r.handed_off
    end
  end

  test "a second high-intent message does not double-enqueue" do
    c = convo
    ConciergeService.ingest(conversation: c, channel: "sms", body: "ready",
                            signals: { "preapproval" => "true", "move_timeline_days" => "20" })
    assert_no_difference "HandoffPacket.count" do
      ConciergeService.ingest(conversation: c, channel: "voice", body: "still ready")
    end
  end

  test "a voice message is recorded as AI-disclosed" do
    c = convo
    r = ConciergeService.ingest(conversation: c, channel: "voice", body: "hello")
    assert r.message.ai_disclosed
  end

  test "an unknown channel is rejected" do
    assert_raises(ArgumentError) { ConciergeService.ingest(conversation: convo, channel: "fax", body: "x") }
  end
end
