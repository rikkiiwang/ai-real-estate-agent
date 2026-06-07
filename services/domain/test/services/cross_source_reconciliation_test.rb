require "test_helper"

class CrossSourceReconciliationTest < ActiveSupport::TestCase
  def listing(address: "100 Test St, Austin, TX 78704", region: "Zilker", price: 600_000, sqft: 2000)
    Property.create!(address: address, state: "listed", region: region,
                     list_price: price, sqft: sqft, beds: 3, baths: 2,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)
  end

  def tax!(address, value)
    PropertyRecordCache.create!(address: address, region: "Zilker", sqft: 2000,
                                tax_assessed_value: value, captured_at: Time.current)
  end

  def market!(zip: "78704", area: "Zilker", median: 580_000, ppsf: 270, dom: 18)
    MarketSnapshot.create!(zip: zip, area: area, median_price: median,
                           avg_price_per_sqft: ppsf, avg_days_on_market: dom,
                           new_listings: 4, as_of: Date.new(2026, 6, 5), source: "Curated Austin sample")
  end

  def usable_valuation(estimate = 620_000)
    BrainValuationClient::Result.new(sufficient_data: true, estimate: estimate,
      low: estimate * 0.9, high: estimate * 1.1, facts: [], as_of: nil, error: nil)
  end

  test "all four sources reconcile with correct deltas, citations, and a signal" do
    prop = listing
    tax!(prop.address, 500_000)
    market!

    r = CrossSourceReconciliation.for(property: prop, valuation: usable_valuation(620_000))

    assert r.available?
    assert_equal 4, r.sources.size
    assert_equal %w[listing:rentcast avm:atlas tax:tcad market:rentcast:78704], r.sources.map(&:source_id)
    assert_equal 600_000, r.asking
    assert_equal 620_000, r.estimate
    assert_equal 500_000, r.tax_assessed
    assert_equal 580_000, r.market_median
    assert_equal 270, r.market_ppsf
    assert_equal 300, r.subject_ppsf
    assert_equal 20, r.asking_vs_tax_pct           # (600-500)/500
    assert_equal 11, r.subject_ppsf_vs_market_pct  # (300-270)/270
    assert_equal :hot, r.signal                    # 300/270 = 1.11 >= 1.08
    assert_match(/\$300\/sqft vs \$270\/sqft/, r.signal_reason)
    assert_match(/~18 days/, r.signal_reason)
  end

  test "missing tax record is reported honestly, not invented" do
    prop = listing
    market!
    r = CrossSourceReconciliation.for(property: prop, valuation: usable_valuation)

    assert_nil r.tax_assessed
    assert_nil r.asking_vs_tax_pct
    assert_not_includes r.sources.map(&:source_id), "tax:tcad"
    assert r.available? # asking + estimate + market = 3
  end

  test "missing market yields no signal and no market source" do
    prop = listing
    tax!(prop.address, 500_000)
    r = CrossSourceReconciliation.for(property: prop, valuation: usable_valuation)

    assert_nil r.market_ppsf
    assert_nil r.signal
    assert_nil r.subject_ppsf_vs_market_pct
    assert_not_includes r.sources.map(&:source_id), "market:rentcast:78704"
  end

  test "a lone asking price is not enough to reconcile" do
    r = CrossSourceReconciliation.for(property: listing) # no valuation, tax, or market
    assert_equal ["listing:rentcast"], r.sources.map(&:source_id)
    refute r.available?
    assert_nil r.signal
  end

  test "market resolves by ZIP parsed from the address" do
    prop = listing(address: "5 River Rd, Austin, TX 78704", region: "Zilker")
    market!(zip: "78704", area: "SomewhereElse")
    r = CrossSourceReconciliation.for(property: prop)
    assert_equal 580_000, r.market_median
  end

  test "a 5-digit street number is not mistaken for the ZIP" do
    prop = listing(address: "12345 Research Blvd, Austin, TX 78759", region: "Zilker")
    market!(zip: "78759", area: "Nowhere")       # the real ZIP
    market!(zip: "12345", area: "AlsoNowhere", median: 999_999) # the street number, as a trap
    r = CrossSourceReconciliation.for(property: prop)
    assert_equal 580_000, r.market_median        # resolved by the trailing ZIP 78759, not 12345
  end

  test "market falls back to the region name when no ZIP matches" do
    prop = listing(address: "5 River Rd, Austin TX", region: "Crestview") # no 5-digit zip
    market!(zip: "73301", area: "Crestview")
    r = CrossSourceReconciliation.for(property: prop)
    assert_equal 580_000, r.market_median
  end

  test "signal thresholds: balanced and cool" do
    market! # ZIP 78704 market at $270/sqft

    balanced = CrossSourceReconciliation.for(property: listing(address: "2 B St, Austin TX 78704", price: 560_000))
    assert_equal :balanced, balanced.signal # 280 vs 270 = 1.037

    cool = CrossSourceReconciliation.for(property: listing(address: "3 C St, Austin TX 78704", price: 480_000))
    assert_equal :cool, cool.signal # 240 vs 270 = 0.888
  end
end
