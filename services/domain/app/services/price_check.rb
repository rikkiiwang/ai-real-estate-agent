# Answers a buyer's pricing question on a listing the way a person would: it
# compares the asking price against Atlas's valuation AND the nearby recent
# sales, then states a plain verdict. The marketplace owns the asking price and
# the comps (the brain only values an address), so this is composed Rails-side —
# cited, useful, and works without an LLM. The model's raw feature attributions
# move into the collapsible reasoning, not the headline.
class PriceCheck
  # Fires only for pricing-flavoured questions asked on a listing.
  INTENT = /\b(priced?|pricing|worth|valuation|over[-\s]?priced|under[-\s]?priced|
              fair(ly)?|deal|expensive|cheap|comps?|comparable|nearby\ sales?|
              good\ (buy|deal)|too\ (high|much|low)|market\ value|a\ steal|overvalued|undervalued)\b/ix

  def self.pricing_question?(text)
    text.to_s.match?(INTENT)
  end

  Result = Struct.new(
    :asking, :estimate, :low, :high, :comps, :comp_median,
    :vs_estimate_pct, :vs_estimate_word, :vs_comps_word, :verdict, :facts, :usable,
    keyword_init: true
  ) do
    def usable? = usable
  end

  def self.for(property:, valuation:, comps:)
    asking = property.list_price.to_i
    return Result.new(usable: false) unless valuation&.usable? && asking.positive?

    estimate = valuation.estimate.to_i
    prices = comps.map { |c| c.sale_price.to_i }.sort
    median = prices.empty? ? nil : prices[prices.size / 2]

    pct = ((asking - estimate).to_f / estimate * 100).round
    vs_estimate = if pct <= -3 then "below"
                  elsif pct >= 3 then "above"
                  else "in line with"
                  end
    vs_comps = if median.nil? then nil
               elsif asking <= median * 0.97 then "below"
               elsif asking >= median * 1.03 then "above"
               else "in line with"
               end

    verdict =
      if pct <= -3 && vs_comps != "above"
        "looks well-priced"
      elsif pct >= 3 && vs_comps != "below"
        "priced at a premium"
      else
        "fairly priced"
      end

    Result.new(
      usable: true, asking: asking, estimate: estimate,
      low: valuation.low.to_i, high: valuation.high.to_i,
      comps: comps, comp_median: median, vs_estimate_pct: pct.abs,
      vs_estimate_word: vs_estimate, vs_comps_word: vs_comps,
      verdict: verdict, facts: valuation.facts
    )
  end
end
