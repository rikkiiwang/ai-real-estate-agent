require "test_helper"

class PropertyRecordPrewarmTest < ActiveSupport::TestCase
  class FakeClient
    attr_reader :calls
    def initialize(records) = (@records = records; @calls = 0)
    def configured? = true
    def property_record(address:)
      @calls += 1
      @records[address]
    end
  end

  test "caps the number of RentCast calls and is cache-first" do
    records = {
      "1 A St" => { "bedrooms" => 3, "bathrooms" => 2, "squareFootage" => 1500,
                    "yearBuilt" => 1990, "latitude" => 30.2, "longitude" => -97.7,
                    "taxAssessments" => { "2025" => { "value" => 410_000 } } },
      "2 B St" => { "bedrooms" => 4, "bathrooms" => 3, "squareFootage" => 2200 },
    }
    client = FakeClient.new(records)
    # Already-fresh cache row should be skipped.
    PropertyRecordCache.create!(address: "2 B St", sqft: 2200, captured_at: 1.hour.ago)

    result = PropertyRecordPrewarm.new(client: client).call(addresses: ["1 A St", "2 B St"], max_calls: 5)

    assert_equal 1, client.calls                    # only the missing one fetched
    assert PropertyRecordCache.find_by("lower(address)=?", "1 a st").sqft == 1500
    assert_equal 1, result.fetched
    assert_equal 1, result.skipped_fresh
  end

  test "refuses to exceed max_calls" do
    records = Hash.new { |h, k| h[k] = { "bedrooms" => 3, "bathrooms" => 2, "squareFootage" => 1500 } }
    client = FakeClient.new(records)
    addresses = (1..10).map { |i| "#{i} St" }

    result = PropertyRecordPrewarm.new(client: client).call(addresses: addresses, max_calls: 3)

    assert_equal 3, client.calls
    assert_equal 3, result.fetched
    assert_equal 7, result.skipped_budget
  end
end
