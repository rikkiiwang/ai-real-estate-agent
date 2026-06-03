require "test_helper"

class DecisionBundleTest < ActiveSupport::TestCase
  def setup
    @listing = Property.create!(address: "1 Mueller", state: "listed", region: "Mueller", list_price: 625_000)
    Comp.create!(region: "Mueller", address: "9 Comp", sale_price: 612_000, sale_date: Date.new(2026, 3, 1), source_name: "TCAD")
    Comp.create!(region: "Mueller", address: "8 Comp", sale_price: 640_000, sale_date: Date.new(2026, 2, 1), source_name: "TCAD")
  end

  test "AE1: bundle carries a sourced rate, tax, comps and a computed monthly payment" do
    bundle = DecisionBundle.for(property: @listing)

    assert bundle.mortgage_rate.value.positive?
    assert bundle.mortgage_rate.source.present?
    assert bundle.mortgage_rate.as_of.present?

    assert bundle.tax_rate.value.positive?
    assert bundle.tax_rate.source.present?

    assert bundle.comps_available?
    assert_operator bundle.comps.size, :>=, 2
    assert bundle.comps.first.source_name.present?

    assert bundle.monthly_payment.positive?
    assert_equal bundle.monthly_principal_interest + bundle.monthly_tax, bundle.monthly_payment
    # Assumptions are exposed alongside the number.
    assert_equal 625_000, bundle.assumptions[:offer_amount]
    assert bundle.assumptions[:rate_pct].positive?
  end

  test "amortization: P&I matches the standard formula for a known loan" do
    # $500k loan, 6.83% (the seeded rate), 30 years.
    listing = Property.create!(address: "2 X", state: "listed", list_price: 625_000)
    bundle = DecisionBundle.for(property: listing, offer_amount: 625_000, down_payment_pct: 20, term_years: 30)
    # 20% down on 625k -> 500k loan.
    assert_equal 500_000, bundle.loan_amount

    r = 6.83 / 100 / 12
    n = 360
    factor = (1 + r)**n
    expected = (500_000 * r * factor / (factor - 1)).round
    assert_in_delta expected, bundle.monthly_principal_interest, 1
  end

  test "100% down means zero principal & interest" do
    bundle = DecisionBundle.for(property: @listing, down_payment_pct: 100)
    assert_equal 0, bundle.loan_amount
    assert_equal 0, bundle.monthly_principal_interest
    assert_equal bundle.monthly_tax, bundle.monthly_payment
  end

  test "0% down finances the full amount" do
    bundle = DecisionBundle.for(property: @listing, offer_amount: 625_000, down_payment_pct: 0)
    assert_equal 625_000, bundle.loan_amount
    assert bundle.monthly_principal_interest.positive?
  end

  test "no comps in a region returns no comparables rather than fabricating" do
    lonely = Property.create!(address: "3 Nowhere", state: "listed", region: "Outpost", list_price: 400_000)
    bundle = DecisionBundle.for(property: lonely)
    assert_not bundle.comps_available?
    assert_empty bundle.comps
  end
end
