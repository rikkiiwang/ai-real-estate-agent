# Rails-side fallback for the TREC blanks-only fill, used when the Python Closer
# is unreachable. Mirrors the Closer's discipline: factual blanks only, no
# authored clause language (there is no clause field — the UPL boundary is
# structural here too).
class ContractDraft
  FORM_ID = "TREC-1-4-RESALE"
  TITLE = "One to Four Family Residential Contract (Resale)"
  EARNEST_RATE = 0.01

  def self.fill(offer)
    blanks = JSON.parse(offer.form_json.presence || "{}")
    address = blanks["property_address"].presence || offer.property&.address.to_s
    buyer = offer.side == "buyer" ? (blanks["buyer_name"].presence || "Represented Buyer") : "Atlas Homes LLC"
    seller = offer.side == "seller" ? (blanks["seller_name"].presence || "Represented Seller") : "Atlas Homes LLC"

    {
      "form_id" => FORM_ID,
      "title" => TITLE,
      "blanks" => {
        "property_address" => address,
        "buyer_name" => buyer,
        "seller_name" => seller,
        "sales_price" => offer.amount.to_f,
        "earnest_money" => (offer.amount.to_f * EARNEST_RATE).round(2),
        "effective_date" => Date.current.iso8601,
        "closing_date" => (Date.current + 30).iso8601
      },
      "selected_contingencies" => []
    }
  end
end
