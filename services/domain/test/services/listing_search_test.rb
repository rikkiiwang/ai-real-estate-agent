require "test_helper"

class ListingSearchTest < ActiveSupport::TestCase
  def setup
    @mueller_low  = Property.create!(address: "1 M", state: "listed", region: "Mueller", list_price: 600_000, beds: 3)
    @mueller_high = Property.create!(address: "2 M", state: "listed", region: "Mueller", list_price: 800_000, beds: 4)
    @tarry        = Property.create!(address: "3 T", state: "listed", region: "Tarrytown", list_price: 650_000, beds: 3)
    # Not browsable: acquired (no listing) and listed-without-price.
    Property.create!(address: "4 X", state: "acquired", region: "Mueller", list_price: 500_000)
    Property.create!(address: "5 Y", state: "listed", region: "Mueller")
  end

  test "no filters returns all browsable listings ordered by price" do
    results = ListingSearch.new.results
    assert_equal [@mueller_low, @tarry, @mueller_high], results.to_a
  end

  test "filters by region" do
    results = ListingSearch.new(region: "Mueller").results
    assert_equal [@mueller_low, @mueller_high], results.to_a
  end

  test "price range is inclusive at both bounds" do
    results = ListingSearch.new(price_min: 600_000, price_max: 800_000).results
    assert_includes results, @mueller_low
    assert_includes results, @mueller_high
  end

  test "min beds filters at the boundary" do
    results = ListingSearch.new(beds: 4).results
    assert_equal [@mueller_high], results.to_a
  end

  test "strips currency formatting from price input" do
    search = ListingSearch.new(price_min: "$600,000")
    assert_equal 600_000, search.price_min
  end

  test "ignores unparseable price input rather than erroring" do
    search = ListingSearch.new(price_max: "lots")
    assert_nil search.price_max
    assert_not search.filtered?
  end

  test "regions lists only regions with browsable listings" do
    assert_equal %w[Mueller Tarrytown], ListingSearch.regions
  end
end
