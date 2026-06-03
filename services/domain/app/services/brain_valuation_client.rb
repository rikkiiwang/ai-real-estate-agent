require "realestate/v1/realestate_services_pb"

# Calls the brain's Valuation.GetValuation RPC for a source-cited home valuation
# (used by the seller workspace). Degrades gracefully when the brain is
# unreachable. Inject a fake `stub:` in tests.
class BrainValuationClient
  Fact = Struct.new(:source_id, :kind, :description, :contribution, keyword_init: true)

  Result = Struct.new(:sufficient_data, :estimate, :low, :high, :facts, :error, keyword_init: true) do
    def ok? = error.nil?
    def usable? = ok? && sufficient_data && estimate.to_f.positive?
  end

  def initialize(stub: nil, addr: nil)
    @stub = stub
    @addr = addr || ENV.fetch("BRAIN_ADDR", "127.0.0.1:50151")
  end

  def valuation(address:)
    resp = stub.get_valuation(Realestate::V1::GetValuationRequest.new(address: address.to_s))
    Result.new(
      sufficient_data: resp.sufficient_data,
      estimate: resp.estimate,
      low: resp.low,
      high: resp.high,
      facts: resp.facts.map { |f| Fact.new(source_id: f.source_id, kind: f.kind, description: f.description, contribution: f.contribution) },
      error: nil
    )
  rescue StandardError => e
    Rails.logger.warn("[brain] valuation failed: #{e.class}: #{e.message}")
    Result.new(sufficient_data: false, estimate: 0, facts: [], error: "valuation_unavailable")
  end

  private

  def stub
    @stub ||= Realestate::V1::Valuation::Stub.new(@addr, :this_channel_is_insecure)
  end
end
