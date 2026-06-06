# services/domain/test/services/subject_resolver_test.rb
require "test_helper"

class SubjectResolverTest < ActiveSupport::TestCase
  test "resolves real attributes from an existing Property" do
    Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 500_000, sqft: 2000, beds: 4, baths: 2.5,
                     year_built: 1998, lat: 30.24, lng: -97.77,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)

    s = SubjectResolver.new(address: "1 oak st").call

    assert s.present?
    assert_equal "Austin 78704", s.region
    assert_equal 2000, s.sqft
    assert_equal 4.0, s.beds
    assert_in_delta 30.24, s.latitude, 0.001
  end

  test "returns nil when the address is not in cache" do
    assert_nil SubjectResolver.new(address: "999 Unknown Rd").call
  end

  test "prefers the active listing over a retired one at the same address" do
    Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 300_000, sqft: 1400, beds: 3, baths: 1.0,
                     retired_at: 1.week.ago,
                     source_name: "RentCast (live listing data)", captured_at: 1.week.ago)
    Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 500_000, sqft: 2000, beds: 4, baths: 2.5,
                     retired_at: nil,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)

    s = SubjectResolver.new(address: "1 Oak St").call

    assert_equal 2000, s.sqft   # active row, not the retired one's 1400
  end
end
