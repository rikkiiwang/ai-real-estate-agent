# Cross-references the independent sources we already hold for a listing — the
# asking price (RentCast listing), the county tax-assessed value (TCAD, via the
# property-record cache), Atlas's AVM estimate (the brain), and the ZIP market
# (median + $/sqft + days-on-market) — into one cited, reconciled view, and
# derives an honest neighborhood signal from it. (PRD R1.)
#
# Rails owns this business reconciliation; the brain stays a pure AVM. DB-only —
# no RentCast, no network. Every figure is cited to its real source with an "as
# of"; a missing source is reported honestly, never invented. Asking ≠ sale ≠
# tax-assessed ≠ model estimate — each is labeled as exactly what it is.
class CrossSourceReconciliation
  # $/sqft this far above/below the ZIP market reads as a hot/cool market.
  HOT_RATIO = 1.08
  COOL_RATIO = 0.92

  Source = Struct.new(:label, :value, :source_id, :as_of, keyword_init: true)

  Result = Struct.new(
    :asking, :estimate, :tax_assessed, :market_median, :market_ppsf, :subject_ppsf,
    :asking_vs_tax_pct, :subject_ppsf_vs_market_pct, :signal, :signal_reason,
    :sources, :available, keyword_init: true
  ) do
    def available? = available
  end

  def self.for(property:, valuation: nil)
    new(property: property, valuation: valuation).call
  end

  def initialize(property:, valuation: nil)
    @property = property
    @valuation = valuation
  end

  def call
    asking = @property.list_price.to_i
    sqft = @property.sqft.to_i
    estimate = @valuation&.usable? ? @valuation.estimate.to_i : nil
    tax = tax_record
    market = market_snapshot

    market_ppsf = market&.avg_price_per_sqft&.to_f&.round
    subject_ppsf = (asking.positive? && sqft.positive?) ? (asking.to_f / sqft).round : nil
    signal, reason = derive_signal(subject_ppsf, market_ppsf, market)

    sources = build_sources(asking, estimate, tax, market)

    Result.new(
      asking: asking,
      estimate: estimate,
      tax_assessed: tax&.tax_assessed_value&.to_i,
      market_median: market&.median_price&.to_i,
      market_ppsf: market_ppsf,
      subject_ppsf: subject_ppsf,
      asking_vs_tax_pct: pct(asking, tax&.tax_assessed_value&.to_i),
      subject_ppsf_vs_market_pct: pct(subject_ppsf, market_ppsf),
      signal: signal,
      signal_reason: reason,
      sources: sources,
      available: sources.size >= 2
    )
  end

  private

  def build_sources(asking, estimate, tax, market)
    sources = []
    sources << Source.new(label: "Asking price", value: asking, source_id: "listing:rentcast",
                          as_of: @property.captured_at) if asking.positive?
    if estimate
      sources << Source.new(label: "Atlas estimate (AVM)", value: estimate, source_id: "avm:atlas",
                            as_of: (@valuation.respond_to?(:as_of) ? @valuation.as_of : nil))
    end
    if tax&.tax_assessed_value
      sources << Source.new(label: "County tax assessment", value: tax.tax_assessed_value.to_i,
                            source_id: "tax:tcad", as_of: tax.captured_at)
    end
    if market&.median_price
      sources << Source.new(label: "ZIP market median", value: market.median_price.to_i,
                            source_id: "market:rentcast:#{market.zip}", as_of: market.as_of)
    end
    sources
  end

  # :hot / :balanced / :cool from $/sqft vs the ZIP market, with a cited reason.
  # nil when there's no market $/sqft to compare against (honest — no signal).
  def derive_signal(subject_ppsf, market_ppsf, market)
    return [nil, nil] unless subject_ppsf && market_ppsf && market_ppsf.positive?

    ratio = subject_ppsf.to_f / market_ppsf
    dom = market.avg_days_on_market&.to_i
    dom_phrase = dom ? "; homes here sell in ~#{dom} days" : ""
    base = "asking $#{subject_ppsf}/sqft vs $#{market_ppsf}/sqft ZIP market#{dom_phrase}"

    if ratio >= HOT_RATIO
      [:hot, "Priced above the neighborhood — #{base}"]
    elsif ratio <= COOL_RATIO
      [:cool, "Priced below the neighborhood — #{base}"]
    else
      [:balanced, "In line with the neighborhood — #{base}"]
    end
  end

  def tax_record
    return nil unless defined?(PropertyRecordCache)

    PropertyRecordCache.find_by("lower(address) = ?", @property.address.to_s.downcase)
  end

  # ZIP from the address (seeded regions are neighborhood names; the ZIP lives in
  # the address), else fall back to a snapshot keyed by the region name. Take the
  # LAST 5-digit token so a 5-digit street number ("12345 Research Blvd ... 78759")
  # is never mistaken for the ZIP.
  def market_snapshot
    zip = @property.address.to_s.scan(/\b\d{5}\b/).last
    (zip && MarketSnapshot.find_by(zip: zip)) || MarketSnapshot.find_by(area: @property.region)
  end

  def pct(a, b)
    return nil unless a && b && b.to_f.positive?

    ((a - b).to_f / b * 100).round
  end
end
