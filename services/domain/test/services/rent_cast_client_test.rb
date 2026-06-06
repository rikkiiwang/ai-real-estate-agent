require "test_helper"

class RentCastClientTest < ActiveSupport::TestCase
  test "property_record returns nil without an api key (no network)" do
    assert_nil RentCastClient.new(api_key: nil).property_record(address: "1 Oak St")
  end
end
