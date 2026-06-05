# The one entry point for an inbound Concierge message on any channel. It appends
# the turn to the unified thread, merges any neutral signals it carried, re-runs
# intent triage, and — the first time a contact becomes high-intent — routes it
# into the EXISTING broker handoff queue (a Lead + a HandoffPacket), so a human
# engages ready parties. Transport is simulated; this owns the thread + routing.
class ConciergeService
  Result = Struct.new(:message, :triage, :handed_off, keyword_init: true)

  def self.ingest(conversation:, channel:, body:, signals: {}, role: "visitor")
    new(conversation).ingest(channel:, body:, signals:, role:)
  end

  def initialize(conversation)
    @conversation = conversation
  end

  def ingest(channel:, body:, signals: {}, role: "visitor")
    raise ArgumentError, "unknown channel #{channel.inspect}" unless Channel.valid?(channel)

    message = nil
    triage = nil
    newly_handed_off = false

    Conversation.transaction do
      message = @conversation.messages.create!(
        channel: channel,
        role: role,
        body: body,
        # On a voice call, AI disclosure is mandatory and assumed delivered up
        # front; text channels carry the voluntary disclosure flag.
        ai_disclosed: Channel.mandatory_disclosure?(channel)
      )

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

    Result.new(message: message, triage: triage, handed_off: newly_handed_off)
  end

  private

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
