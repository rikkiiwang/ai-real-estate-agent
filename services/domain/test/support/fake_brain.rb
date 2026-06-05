# A deterministic, offline stand-in for BrainConversationClient so Concierge
# tests (and seed loading in tests) never make a real gRPC call to the brain.
class FakeBrain
  Reply = Struct.new(:message, :claims, :handoff, :escalated, keyword_init: true)

  def orchestrate(query:, **)
    Reply.new(message: "Atlas: a grounded reply to “#{query}”.", claims: [], escalated: false)
  end
end
