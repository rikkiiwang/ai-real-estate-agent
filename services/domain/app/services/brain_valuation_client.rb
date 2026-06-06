require "realestate/v1/realestate_services_pb"

# Calls the brain's Valuation.GetValuation RPC for a source-cited home valuation
# (used by the seller workspace). Degrades gracefully when the brain is
# unreachable. Inject a fake `stub:` in tests.
class BrainValuationClient
  Fact = Struct.new(:source_id, :kind, :description, :contribution, keyword_init: true)

  Result = Struct.new(:sufficient_data, :estimate, :low, :high, :facts,
                      :as_of, :recent_activity, :error, keyword_init: true) do
    def ok? = error.nil?
    def usable? = ok? && sufficient_data && estimate.to_f.positive?
  end

  def initialize(stub: nil, addr: nil)
    @stub = stub
    @addr = addr || ENV.fetch("BRAIN_ADDR", "127.0.0.1:50151")
  end

  def valuation(address:, features: nil, comps: nil, as_of: nil, recent_activity: nil)
    req = Realestate::V1::GetValuationRequest.new(
      address: address.to_s,
      as_of: as_of.to_s,
      recent_activity: recent_activity.to_s,
    )
    req.features = build_features(features) if features.present?
    Array(comps).each { |c| req.comps << build_comp(c) }

    resp = stub.get_valuation(req)
    Result.new(
      sufficient_data: resp.sufficient_data,
      estimate: resp.estimate, low: resp.low, high: resp.high,
      facts: resp.facts.map { |f| Fact.new(source_id: f.source_id, kind: f.kind, description: f.description, contribution: f.contribution) },
      as_of: resp.as_of.presence,
      recent_activity: resp.recent_activity.presence,
      error: nil,
    )
  rescue StandardError => e
    Rails.logger.warn("[brain] valuation failed: #{e.class}: #{e.message}")
    Result.new(sufficient_data: false, estimate: 0, facts: [], error: "valuation_unavailable")
  end

  private

  def build_features(f)
    Realestate::V1::PropertyFeatures.new(
      beds: f[:beds].to_f, baths: f[:baths].to_f, sqft: f[:sqft].to_f,
      lot_sqft: f[:lot_sqft].to_f, year_built: f[:year_built].to_i,
      latitude: f[:latitude].to_f, longitude: f[:longitude].to_f,
      garage_spaces: f[:garage_spaces].to_f,
      condition: f[:condition].to_f, has_condition: !f[:condition].nil?,
    )
  end

  def build_comp(c)
    Realestate::V1::CompInput.new(
      id: c.id.to_s, price: c.price.to_f, sqft: c.sqft.to_f, beds: c.beds.to_f,
      baths: c.baths.to_f, distance_mi: c.distance_mi.to_f,
      age_days: c.age_days.to_i, address: c.address.to_s,
    )
  end

  def stub
    @stub ||= Realestate::V1::Valuation::Stub.new(@addr, :this_channel_is_insecure)
  end
end
