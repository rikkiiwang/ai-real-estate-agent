# services/domain/test/services/comps_selector_test.rb
require "test_helper"

class CompsSelectorTest < ActiveSupport::TestCase
  def listing(addr:, region:, price:, sqft:, beds: 3, captured: Time.current)
    Property.create!(address: addr, state: "listed", region: region,
                     list_price: price, sqft: sqft, beds: beds, baths: 2,
                     source_name: "RentCast (live listing data)", captured_at: captured)
  end

  test "selects same-region browsable listings, excludes the subject itself" do
    subject = listing(addr: "1 Oak St", region: "Austin 78704", price: 500_000, sqft: 2000)
    listing(addr: "2 Oak St", region: "Austin 78704", price: 520_000, sqft: 2050)
    listing(addr: "9 Far Ave", region: "Austin 78759", price: 900_000, sqft: 2100)

    comps = CompsSelector.new(region: "Austin 78704", exclude_address: "1 Oak St").call(limit: 5)

    addrs = comps.map(&:address)
    assert_includes addrs, "2 Oak St"
    refute_includes addrs, "1 Oak St"      # subject excluded
    refute_includes addrs, "9 Far Ave"     # different region excluded
  end

  test "excludes retired and price-less listings, returns CompInput-shaped structs" do
    listing(addr: "2 Oak St", region: "Austin 78704", price: 520_000, sqft: 2050)
    Property.create!(address: "3 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 500_000, sqft: 2000, retired_at: Time.current,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)

    comps = CompsSelector.new(region: "Austin 78704", exclude_address: "1 Oak St").call(limit: 5)

    assert_equal ["2 Oak St"], comps.map(&:address)
    c = comps.first
    assert_equal 520_000.0, c.price
    assert_equal 2050, c.sqft
    assert c.age_days >= 0
  end

  test "limit caps the number returned" do
    6.times { |i| listing(addr: "#{i} Oak St", region: "Austin 78704", price: 500_000 + i, sqft: 2000) }
    comps = CompsSelector.new(region: "Austin 78704", exclude_address: "z").call(limit: 4)
    assert_equal 4, comps.size
  end
end
