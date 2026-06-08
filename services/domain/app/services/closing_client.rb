require "realestate/v1/realestate_services_pb"

# gRPC client for Closer.RecordMilestone (R10). Asks the brain to route a met
# milestone to its counterparty and emit the (simulated) ping. Mirrors
# CloserClient: same Closer stub, BRAIN_ADDR, and graceful degradation — a
# transport failure returns an error Result so the caller can fall back.
class ClosingClient
  Result = Struct.new(:pinged, :counterparty, :message, :error, keyword_init: true) do
    def ok? = error.nil?
  end

  def initialize(stub: nil, addr: nil)
    @stub = stub
    @addr = addr || ENV.fetch("BRAIN_ADDR", "127.0.0.1:50151")
  end

  def record_milestone(deal_id:, milestone:)
    resp = stub.record_milestone(
      Realestate::V1::RecordMilestoneRequest.new(deal_id: deal_id.to_s, milestone: milestone.to_s)
    )
    Result.new(pinged: resp.pinged, counterparty: resp.counterparty, message: resp.message, error: nil)
  rescue StandardError => e
    Rails.logger.warn("[brain] record_milestone failed: #{e.class}: #{e.message}")
    Result.new(pinged: false, error: "closing_unavailable")
  end

  private

  def stub
    @stub ||= Realestate::V1::Closer::Stub.new(@addr, :this_channel_is_insecure)
  end
end
