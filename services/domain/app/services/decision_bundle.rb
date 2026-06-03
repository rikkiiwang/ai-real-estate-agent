# Assembles the buyer's cited decision bundle for an offer: current mortgage
# rate, nearby comps, the annual property-tax rate, and the resulting estimated
# monthly payment. Every figure carries a source. Pure Rails (no brain
# round-trip) so "make an offer" is instant and reliable. Never fabricates
# comps — if a region has no recorded sales, it says so (R14: no source, no
# claim).
class DecisionBundle
  Sourced = Struct.new(:value, :source, :source_url, :as_of, keyword_init: true)

  attr_reader :property, :offer_amount, :down_payment_pct, :term_years

  def self.for(property:, offer_amount: nil, down_payment_pct: nil, term_years: nil)
    new(property: property, offer_amount: offer_amount,
        down_payment_pct: down_payment_pct, term_years: term_years)
  end

  def initialize(property:, offer_amount: nil, down_payment_pct: nil, term_years: nil)
    @property = property
    @offer_amount = (offer_amount.presence || property.list_price).to_i
    @down_payment_pct = (down_payment_pct.presence || MarketConfig.default_down_payment_pct).to_f
    @term_years = (term_years.presence || MarketConfig.default_term_years).to_i
  end

  # The 30-year fixed rate, with source + as-of date.
  def mortgage_rate
    cfg = MarketConfig.mortgage_rate
    Sourced.new(value: cfg[:value].to_f, source: cfg[:source], source_url: cfg[:source_url], as_of: cfg[:as_of])
  end

  # The effective annual property-tax rate, with source + as-of date.
  def tax_rate
    cfg = MarketConfig.tax_rate
    Sourced.new(value: cfg[:value].to_f, source: cfg[:source], source_url: cfg[:source_url], as_of: cfg[:as_of])
  end

  def comps
    @comps ||= Comp.in_region(property.region).recent_first.limit(3).to_a
  end

  def comps_available?
    comps.any?
  end

  def down_payment
    (offer_amount * down_payment_pct / 100.0).round
  end

  def loan_amount
    offer_amount - down_payment
  end

  # Principal & interest portion of the monthly payment (standard amortization).
  def monthly_principal_interest
    r = mortgage_rate.value / 100.0 / 12.0
    n = term_years * 12
    return (loan_amount.to_f / n).round if r.zero?

    factor = (1 + r)**n
    (loan_amount * r * factor / (factor - 1)).round
  end

  # Monthly share of annual property tax.
  def monthly_tax
    (offer_amount * tax_rate.value / 100.0 / 12.0).round
  end

  def monthly_payment
    monthly_principal_interest + monthly_tax
  end

  def assumptions
    {
      offer_amount: offer_amount,
      down_payment_pct: down_payment_pct,
      down_payment: down_payment,
      loan_amount: loan_amount,
      term_years: term_years,
      rate_pct: mortgage_rate.value
    }
  end
end
