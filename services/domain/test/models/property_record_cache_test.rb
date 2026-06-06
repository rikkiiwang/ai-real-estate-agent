require "test_helper"

class PropertyRecordCacheTest < ActiveSupport::TestCase
  test "fresh? reflects the TTL" do
    rec = PropertyRecordCache.new(address: "1 A", captured_at: 1.day.ago)
    assert rec.fresh?
    rec.captured_at = 30.days.ago
    refute rec.fresh?
  end

  test "address uniqueness is case-insensitive" do
    PropertyRecordCache.create!(address: "1 Oak St")
    dup = PropertyRecordCache.new(address: "1 oak st")
    refute dup.valid?
  end
end
