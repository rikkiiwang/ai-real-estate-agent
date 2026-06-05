# The one entry point for an inbound Concierge message on any channel. It appends
# the turn to the unified thread, merges any neutral signals it carried, re-runs
# intent triage, and — the first time a contact becomes high-intent — routes it
# into the EXISTING broker handoff queue (a Lead + a HandoffPacket), so a human
# engages ready parties. Transport is simulated; this owns the thread + routing.
class ConciergeService
  # Test seam: a callable returning a brain conversation client. Nil in
  # production, where the real BrainConversationClient (gRPC) is used.
  cattr_accessor :brain_factory

  Result = Struct.new(:message, :reply, :triage, :handed_off, keyword_init: true)

  def self.ingest(conversation:, channel:, body:, signals: {}, role: "visitor")
    new(conversation).ingest(channel:, body:, signals:, role:)
  end

  def initialize(conversation, brain: nil)
    @conversation = conversation
    @brain = brain || brain_factory&.call || BrainConversationClient.new
  end

  def ingest(channel:, body:, signals: {}, role: "visitor")
    raise ArgumentError, "unknown channel #{channel.inspect}" unless Channel.valid?(channel)

    message = nil
    triage = nil
    newly_handed_off = false

    Conversation.transaction do
      message = append(channel: channel, role: role, body: body)

      @conversation.merge_signals(signals)
      triage = IntentTriage.call(signals: @conversation.signals, side: @conversation.side)
      @conversation.intent = triage.intent

      if triage.high_intent? && !@conversation.handed_off?
        route_to_broker(triage)
        @conversation.handed_off = true
        newly_handed_off = true
      end

      @conversation.save!
    end

    # The embedded chatbot: the same grounded, cited "glass box" agent (brain
    # orchestrator) replies IN-THREAD, on the same channel, to a visitor turn.
    # Runs after the transaction so a slow/failed brain call never rolls back the
    # visitor's message; the client degrades to a friendly fallback on its own.
    reply = role == "visitor" ? agent_reply(channel: channel, query: body) : nil

    Result.new(message: message, reply: reply, triage: triage, handed_off: newly_handed_off)
  end

  private

  def append(channel:, role:, body:)
    @conversation.messages.create!(
      channel: channel,
      role: role,
      body: body,
      # AI messages on a voice call carry the mandatory disclosure; text channels
      # carry the voluntary flag.
      ai_disclosed: Channel.mandatory_disclosure?(channel)
    )
  end

  def agent_reply(channel:, query:)
    result = @brain.orchestrate(
      query: query,
      address: @conversation.signals["address"].to_s, # ground when an address is known
      thread_id: "concierge-#{@conversation.id}"
    )
    body = result.message.to_s.strip
    body = fallback_reply(result) if body.empty?
    append(channel: channel, role: "agent", body: body)
  rescue StandardError => e
    Rails.logger.warn("[concierge] agent reply failed: #{e.class}: #{e.message}")
    nil
  end

  # The grounded agent intentionally returns an empty message for open-ended
  # chit-chat it can't source ("no source -> no claim"), and tends to escalate on
  # low confidence. In the Concierge, a vague turn is NOT a reason to punt to a
  # broker — broker hand-off here is driven by INTENT TRIAGE, not per-message
  # confidence — so reply with a useful next step that keeps the chat moving.
  def fallback_reply(_result)
    "Happy to help! Tell me an address or a neighborhood — plus your budget or must-haves — " \
      "and I'll pull cited specifics: price vs. nearby sales, the monthly payment, and the local market."
  end

  # Reuse the existing broker queue: a Lead carries the triaged intent; a
  # HandoffPacket with trigger "high_intent" lands in HandoffPacket.queue on the
  # broker dashboard. Created at most once per conversation (handed_off guard).
  def route_to_broker(triage)
    address = @conversation.signals["address"].presence ||
              "Engagement lead — #{@conversation.contact.presence || 'concierge'}"

    lead = Lead.create!(
      side: @conversation.side,
      address: address,
      contact: @conversation.contact,
      intent: "high"
    )

    # Canonical enqueue: lands on the broker queue AND records the rail trip to
    # the append-only audit log (why this lead was escalated).
    EnqueueHandoff.call(
      lead: lead,
      trigger: "high_intent",
      reason: triage.reason,
      recommended_action: "Engage high-intent #{@conversation.side} — #{triage.signals_used.join(', ')}",
      transcript: @conversation.messages.map { |m| "[#{m.channel}] #{m.role}: #{m.body}" }.join("\n")
    )
  end
end
