# Accessor for the dated, sourced market reference values (config/marketplace.yml).
# Every value the decision bundle cites comes from here with its source + as-of
# date — no live API.
module MarketConfig
  module_function

  def all
    Rails.application.config_for(:marketplace)
  end

  def mortgage_rate
    all[:mortgage_rate]
  end

  def tax_rate
    all[:property_tax_rate]
  end

  def default_down_payment_pct
    all.dig(:default_assumptions, :down_payment_pct) || 20
  end

  def default_term_years
    all.dig(:default_assumptions, :term_years) || 30
  end
end
