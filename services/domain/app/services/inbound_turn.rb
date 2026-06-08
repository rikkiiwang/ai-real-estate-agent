# The single inbound pipeline shared by SMS / email / voice (R4): find-or-create
# the contact's Conversation, append the inbound turn, run one orchestrator turn
# keyed to the durable thread, append the reply, and return it. Brain-down yields
# a friendly fallback so a webhook never dead-ends.
class InboundTurn
  FALLBACK = "Thanks for reaching out — a licensed Atlas broker will follow up shortly.".freeze

  Result = Struct.new(:conversation, :reply, keyword_init: true)

  def self.call(contact:, channel:, body:, name: nil, client: BrainConversationClient.new)
    convo = Conversation.for(contact: contact, name: name)
    disclosed = Channel.mandatory_disclosure?(channel)
    convo.append(channel: channel, role: "user", body: body, ai_disclosed: disclosed)

    reply =
      begin
        res = client.orchestrate(query: body.to_s, thread_id: convo.thread_id)
        res.message.presence || FALLBACK
      rescue StandardError => e
        Rails.logger.warn("[inbound] orchestrate failed: #{e.class}: #{e.message}")
        FALLBACK
      end

    convo.append(channel: channel, role: "agent", body: reply, ai_disclosed: disclosed)
    Result.new(conversation: convo, reply: reply)
  end
end
