require "realestate/v1/realestate_services_pb"

# Calls the Python brain's Conversation.Orchestrate RPC (the LangGraph agent
# loop) and reshapes the proto response into plain Ruby value objects the
# sidebar can render. Mirrors services/chat/main.go's toChatResponse mapping.
#
# The brain gRPC server is unauthenticated on its internal (flycast) network —
# the same insecure channel the chat service uses. Inject a fake `stub:` in
# tests so specs never touch a live brain.
class BrainConversationClient
  Result = Struct.new(
    :outcome, :escalated, :message, :draft, :sufficient_data, :attempts,
    :confidence, :verify_reason, :coverage, :agreement, :self_consistency,
    :fair_housing_allowed, :fair_housing_reason, :handoff, :claims, :steps,
    :error, keyword_init: true
  ) do
    def ok? = error.nil?
    def handoff? = escalated
  end

  Claim = Struct.new(:claim, :label, :score, :source_kind, :supported, :citation_source_id, :reason, keyword_init: true)
  Step  = Struct.new(:node, :title, :detail, :status, keyword_init: true)
  Handoff = Struct.new(:trigger, :reason, :recommended_action, :hard, keyword_init: true)

  def initialize(stub: nil, addr: nil)
    @stub = stub
    @addr = addr || ENV.fetch("BRAIN_ADDR", "127.0.0.1:50151")
  end

  def orchestrate(query:, address: "", thread_id: nil)
    request = Realestate::V1::OrchestrateRequest.new(
      query: query.to_s, address: address.to_s, thread_id: thread_id.to_s
    )
    to_result(stub.orchestrate(request))
  rescue StandardError => e
    Rails.logger.warn("[brain] orchestrate failed: #{e.class}: #{e.message}")
    Result.new(
      error: "agent_unavailable", outcome: "handoff", escalated: false,
      message: "The assistant is taking a moment to respond. Please try again — your browsing isn't affected.",
      claims: [], steps: []
    )
  end

  private

  def stub
    @stub ||= Realestate::V1::Conversation::Stub.new(@addr, :this_channel_is_insecure)
  end

  def to_result(resp)
    Result.new(
      outcome: resp.outcome,
      escalated: resp.escalated,
      message: resp.final_message,
      draft: resp.draft,
      sufficient_data: resp.sufficient_data,
      attempts: resp.attempts,
      confidence: resp.confidence,
      verify_reason: resp.verification_reason,
      coverage: resp.coverage,
      agreement: resp.agreement,
      self_consistency: resp.self_consistency,
      fair_housing_allowed: resp.fair_housing_allowed,
      fair_housing_reason: resp.fair_housing_reason,
      handoff: handoff_for(resp),
      claims: resp.claims.map { |c| to_claim(c) },
      steps: resp.steps.map { |s| to_step(s) },
      error: nil
    )
  end

  def handoff_for(resp)
    return nil unless resp.escalated || resp.handoff_trigger.present?

    Handoff.new(
      trigger: resp.handoff_trigger,
      reason: resp.handoff_reason,
      recommended_action: resp.handoff_recommended_action,
      hard: resp.hard_trigger
    )
  end

  def to_claim(c)
    Claim.new(
      claim: c.claim, label: c.label, score: c.score, source_kind: c.source_kind,
      supported: c.supported, citation_source_id: c.citation_source_id, reason: c.reason
    )
  end

  def to_step(s)
    Step.new(node: s.node, title: s.title, detail: s.detail, status: s.status)
  end
end
