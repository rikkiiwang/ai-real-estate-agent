require "realestate/v1/realestate_services_pb"

# Calls the brain's Closer.GenerateContract RPC (TREC blanks-only fill). Degrades
# gracefully — a failure returns a non-drafted result so the caller can fall
# back to the Rails-side ContractDraft. Inject a fake `stub:` in tests.
class CloserClient
  Result = Struct.new(:drafted, :form_id, :title, :form_json, :upl_blocked, :handoff_reason, :error, keyword_init: true) do
    def ok? = error.nil?
  end

  def initialize(stub: nil, addr: nil)
    @stub = stub
    @addr = addr || ENV.fetch("BRAIN_ADDR", "127.0.0.1:50151")
  end

  def generate_contract(property_address:, buyer_name:, seller_name:, sales_price:,
                        effective_date:, closing_date:, earnest_money: 0, custom_clause_request: "")
    resp = stub.generate_contract(Realestate::V1::GenerateContractRequest.new(
      property_address: property_address.to_s, buyer_name: buyer_name.to_s,
      seller_name: seller_name.to_s, sales_price: sales_price.to_f,
      earnest_money: earnest_money.to_f, effective_date: effective_date.to_s,
      closing_date: closing_date.to_s, custom_clause_request: custom_clause_request.to_s
    ))
    Result.new(drafted: resp.drafted, form_id: resp.form_id, title: resp.title,
               form_json: resp.form_json, upl_blocked: resp.upl_blocked,
               handoff_reason: resp.handoff_reason, error: nil)
  rescue StandardError => e
    Rails.logger.warn("[brain] generate_contract failed: #{e.class}: #{e.message}")
    Result.new(drafted: false, error: "closer_unavailable")
  end

  private

  def stub
    @stub ||= Realestate::V1::Closer::Stub.new(@addr, :this_channel_is_insecure)
  end
end
