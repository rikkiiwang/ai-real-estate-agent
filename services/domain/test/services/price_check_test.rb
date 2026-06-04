require "test_helper"

class PriceCheckTest < ActiveSupport::TestCase
  Val = Struct.new(:usable, :estimate, :low, :high, :facts, keyword_init: true) do
    def usable? = usable
  end

  def comps(*prices)
    prices.map { |p| Comp.new(region: "Mueller", address: "x", sale_price: p, sale_date: Date.new(2026, 3, 1), source_name: "TCAD") }
  end

  def valuation(estimate)
    Val.new(usable: true, estimate: estimate, low: estimate * 0.9, high: estimate * 1.1, facts: [])
  end

  test "detects pricing questions and ignores non-pricing ones" do
    assert PriceCheck.pricing_question?("Is this fairly priced compared to nearby sales?")
    assert PriceCheck.pricing_question?("is this a good deal?")
    assert PriceCheck.pricing_question?("what's it worth?")
    assert_not PriceCheck.pricing_question?("how many bedrooms does it have?")
    assert_not PriceCheck.pricing_question?("when was it built?")
  end

  test "asking well below the estimate reads as well-priced" do
    listing = Property.new(list_price: 525_000)
    pc = PriceCheck.for(property: listing, valuation: valuation(636_000), comps: comps(610_000, 612_000))
    assert pc.usable?
    assert_equal "below", pc.vs_estimate_word
    assert_operator pc.vs_estimate_pct, :>, 10
    assert_equal "looks well-priced", pc.verdict
    assert_equal 612_000, pc.comp_median # median of [610k, 612k] -> upper of two
  end

  test "asking well above the estimate reads as a premium" do
    listing = Property.new(list_price: 700_000)
    pc = PriceCheck.for(property: listing, valuation: valuation(600_000), comps: comps(590_000, 600_000))
    assert_equal "above", pc.vs_estimate_word
    assert_equal "priced at a premium", pc.verdict
  end

  test "asking near the estimate reads as fairly priced" do
    listing = Property.new(list_price: 605_000)
    pc = PriceCheck.for(property: listing, valuation: valuation(600_000), comps: comps(600_000))
    assert_equal "in line with", pc.vs_estimate_word
    assert_equal "fairly priced", pc.verdict
  end

  test "no comps still produces a usable estimate comparison" do
    listing = Property.new(list_price: 525_000)
    pc = PriceCheck.for(property: listing, valuation: valuation(636_000), comps: [])
    assert pc.usable?
    assert_nil pc.comp_median
  end

  test "an unusable valuation yields a non-usable result (caller falls back)" do
    listing = Property.new(list_price: 525_000)
    pc = PriceCheck.for(property: listing, valuation: Val.new(usable: false), comps: [])
    assert_not pc.usable?
  end
end
