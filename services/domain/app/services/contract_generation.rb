# Generates the TREC blanks-only contract draft when a broker signs an offer.
# Prefers the Python Closer (Closer.GenerateContract) and falls back to a
# Rails-side blanks fill so the flow never dead-ends if the brain is down. The
# result is delivered in-app to both parties as a draft for review (R12, R13).
class ContractGeneration
  EARNEST_RATE = 0.01

  def self.call(offer, closer: nil)
    new(offer, closer: closer || CloserClient.new).call
  end

  def initialize(offer, closer:)
    @offer = offer
    @closer = closer
    @blanks = JSON.parse(offer.form_json.presence || "{}")
  end

  def call
    return @offer.contract if @offer.respond_to?(:contract) && @offer.contract.present?

    result = @closer.generate_contract(**closer_args)

    if result.drafted
      build_contract(form_id: result.form_id, title: result.title, form_json: result.form_json, source: "closer")
    elsif result.error.present?
      # The Closer was UNREACHABLE (transport) — Rails fills the same blanks-only
      # form so the flow never dead-ends.
      fallback = ContractDraft.fill(@offer)
      build_contract(form_id: fallback["form_id"], title: fallback["title"], form_json: fallback.to_json, source: "rails_fallback")
    else
      # The Closer was reachable and REFUSED (UPL custom clause, or invalid
      # facts). Never fabricate a draft over a genuine refusal — escalate by
      # returning nil so the caller routes to a human.
      nil
    end
  end

  private

  def build_contract(form_id:, title:, form_json:, source:)
    Contract.create!(
      offer: @offer, form_id: form_id, title: title, form_json: form_json,
      source: source, status: "draft", delivered_at: Time.current
    )
  end

  def closer_args
    {
      property_address: property_address,
      buyer_name: buyer_name,
      seller_name: seller_name,
      sales_price: @offer.amount.to_f,
      earnest_money: (@offer.amount.to_f * EARNEST_RATE).round(2),
      effective_date: Date.current.iso8601,
      closing_date: (Date.current + 30).iso8601
    }
  end

  def property_address
    @blanks["property_address"].presence || @offer.property&.address.to_s
  end

  # Party names depend on which side the offer is. On a buyer offer the consumer
  # is the buyer and the platform is the counterparty seller; on a seller offer
  # the consumer is the seller and the platform is the buyer.
  def buyer_name
    @offer.side == "buyer" ? (@blanks["buyer_name"].presence || "Represented Buyer") : "Atlas Homes LLC"
  end

  def seller_name
    @offer.side == "seller" ? (@blanks["seller_name"].presence || "Represented Seller") : "Atlas Homes LLC"
  end
end
