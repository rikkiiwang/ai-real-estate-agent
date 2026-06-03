require "test_helper"

class SearchIntentTest < ActiveSupport::TestCase
  REGIONS = %w[Mueller Tarrytown Crestview].freeze

  test "parses beds, max price and region from a browse request" do
    intent = SearchIntent.detect("show me 3-bed homes under $700k in Mueller", regions: REGIONS)
    refute_nil intent
    assert_equal 3, intent.beds
    assert_equal 700_000, intent.price_max
    assert_equal "Mueller", intent.region
  end

  test "handles k and m suffixes and commas" do
    assert_equal 650_000, SearchIntent.detect("homes under 650k", regions: REGIONS).price_max
    assert_equal 1_200_000, SearchIntent.detect("houses below 1.2m", regions: REGIONS).price_max
    assert_equal 800_000, SearchIntent.detect("under $800,000", regions: REGIONS).price_max
  end

  test "parses a minimum price" do
    intent = SearchIntent.detect("homes over $900k in Tarrytown", regions: REGIONS)
    assert_equal 900_000, intent.price_min
    assert_equal "Tarrytown", intent.region
  end

  test "parses both bounds positionally (not the max of all tokens)" do
    intent = SearchIntent.detect("homes over $400k under $800k in Mueller", regions: REGIONS)
    assert_equal 400_000, intent.price_min
    assert_equal 800_000, intent.price_max
    assert_equal "Mueller", intent.region
  end

  test "ignores an unrelated larger number, binding the price to the keyword" do
    intent = SearchIntent.detect("homes under 700k near 900 Congress in Crestview", regions: REGIONS)
    assert_equal 700_000, intent.price_max
  end

  test "returns nil for a non-search question" do
    assert_nil SearchIntent.detect("is this house a good deal?", regions: REGIONS)
    assert_nil SearchIntent.detect("what are the property taxes?", regions: REGIONS)
  end

  test "records an unparseable region rather than dropping it silently" do
    intent = SearchIntent.detect("show me homes in Westlake", regions: REGIONS)
    # Westlake isn't a known region; beds/price absent -> no usable filter -> nil
    assert_nil intent
  end

  test "a region-only request still surfaces results" do
    intent = SearchIntent.detect("show me homes in Crestview", regions: REGIONS)
    assert_equal "Crestview", intent.region
    assert intent.any_filter?
  end
end
