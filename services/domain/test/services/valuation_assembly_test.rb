# frozen_string_literal: true
require "test_helper"

class ValuationAssemblyTest < ActiveSupport::TestCase
  def seed_pool
    Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 500_000, sqft: 2000, beds: 4, baths: 2.5, year_built: 1998,
                     lat: 30.24, lng: -97.77, source_name: "RentCast (live listing data)",
                     captured_at: Time.current)
    Property.create!(address: "2 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 520_000, sqft: 2050, beds: 4, baths: 2,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)
    MarketSnapshot.create!(zip: "78704", area: "Austin 78704", median_price: 600_000,
                           new_listings: 3, avg_days_on_market: 21, as_of: Date.new(2026, 6, 5))
  end

  test "known address: sends real features + comps + recency to the brain" do
    seed_pool
    captured = nil
    client = Object.new
    client.define_singleton_method(:valuation) do |address:, features: nil, comps: nil, as_of: nil, recent_activity: nil|
      captured = { address:, features:, comps:, as_of:, recent_activity: }
      BrainValuationClient::Result.new(sufficient_data: true, estimate: 480_000,
        low: 440_000, high: 520_000, facts: [], as_of: as_of, recent_activity: recent_activity)
    end

    result = ValuationAssembly.new(address: "1 Oak St", client: client).call

    assert result.usable?
    assert_equal 2000, captured[:features][:sqft]                 # real subject sqft
    assert_equal ["2 Oak St"], captured[:comps].map(&:address)    # comp pool, subject excluded
    assert_match(/3 new listing/, captured[:recent_activity])     # honest recency
  end

  test "unknown address: falls back to address-only (no features), still ok" do
    captured = nil
    client = Object.new
    client.define_singleton_method(:valuation) do |address:, features: nil, **kw|
      captured = { features: features }
      BrainValuationClient::Result.new(sufficient_data: true, estimate: 500_000, facts: [])
    end

    result = ValuationAssembly.new(address: "999 Unknown Rd", client: client).call

    assert result.usable?
    assert_nil captured[:features] # honest: no real data => hash fallback, lower confidence
    assert result.low_confidence?
  end

  test "sends the cached photo-derived condition to the brain (R2)" do
    seed_pool
    PhotoAnalysis.create!(address: "1 Oak St", condition: 0.82, provenance: "claude",
                          findings: [], needs_review: [], analyzed_at: Time.current)
    captured = nil
    client = Object.new
    client.define_singleton_method(:valuation) do |address:, features: nil, **kw|
      captured = { features: features }
      BrainValuationClient::Result.new(sufficient_data: true, estimate: 480_000, facts: [])
    end

    ValuationAssembly.new(address: "1 Oak St", client: client).call
    assert_in_delta 0.82, captured[:features][:condition], 0.001 # real condition flows to the AVM
  end

  test "no cached photo analysis => condition is nil (AVM imputes)" do
    seed_pool
    captured = nil
    client = Object.new
    client.define_singleton_method(:valuation) do |address:, features: nil, **kw|
      captured = { features: features }
      BrainValuationClient::Result.new(sufficient_data: true, estimate: 480_000, facts: [])
    end

    ValuationAssembly.new(address: "1 Oak St", client: client).call
    assert_nil captured[:features][:condition]
  end
end
