# The one place a closing milestone is recorded (R10). Every entry point — the
# broker dashboard button and a completed inspection — goes through here, so
# idempotency, canonical order, the counterparty ping, and the audit entry are
# uniform. Rails owns the state; the brain (ClosingClient) routes + emits the
# (simulated) ping. If the brain is unreachable we still record the milestone,
# routing locally and marking the ping "pending" — honest, never a dead-end.
class ClosingOrchestration
  RAILS_ROUTING = ClosingMilestone::MILESTONE_COUNTERPARTY
  ACTION = {
    "inspection_cleared" => "inspection cleared — releasing contingency",
    "earnest_deposited" => "earnest-money deposit triggered",
    "title_cleared" => "title cleared — preparing settlement",
    "funded" => "loan funded — ready to disburse"
  }.freeze

  Result = Struct.new(:recorded, :milestone, :counterparty, :ping_message, :ping_status, :reason, keyword_init: true) do
    def recorded? = recorded
  end

  def self.record(offer:, milestone:, client: ClosingClient.new)
    new(offer: offer, milestone: milestone, client: client).record
  end

  def initialize(offer:, milestone:, client:)
    @offer = offer
    @milestone = milestone.to_s
    @client = client
  end

  def record
    unless ClosingMilestone::MILESTONES.include?(@milestone)
      return Result.new(recorded: false, milestone: @milestone, reason: "unknown milestone")
    end
    if @offer.closing_milestones.exists?(milestone: @milestone)
      return Result.new(recorded: false, milestone: @milestone, reason: "already recorded")
    end
    expected = @offer.next_closing_milestone
    if @milestone != expected
      return Result.new(recorded: false, milestone: @milestone, reason: "complete #{expected} first")
    end

    res = @client.record_milestone(deal_id: @offer.deal_id, milestone: @milestone)
    if res.ok?
      counterparty, message, status = res.counterparty, res.message, "simulated"
    else
      counterparty = RAILS_ROUTING[@milestone]
      message = "Notified #{counterparty}: #{ACTION[@milestone]} for #{@offer.deal_id}. (orchestrator unreachable — ping pending)"
      status = "pending"
    end

    @offer.closing_milestones.create!(
      milestone: @milestone, counterparty: counterparty, ping_message: message,
      ping_status: status, recorded_at: Time.current
    )
    AuditEvent.record_rail_trip(
      kind: "milestone_recorded", decision: @milestone, subject: @offer,
      detail: "#{counterparty} pinged (#{status}): #{message}"
    )
    Result.new(recorded: true, milestone: @milestone, counterparty: counterparty,
               ping_message: message, ping_status: status)
  end
end
