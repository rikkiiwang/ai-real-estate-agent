require "test_helper"

class PropertyTest < ActiveSupport::TestCase
  test "defaults to acquired" do
    property = Property.create!(address: "1 Loop")
    assert_equal "acquired", property.state
  end

  test "full lifecycle acquired -> listed -> under_offer -> sold" do
    property = Property.create!(address: "2 Loop")
    property.list!
    assert_equal "listed", property.state
    property.mark_under_offer!
    assert_equal "under_offer", property.state
    property.sell!
    assert_equal "sold", property.state
  end

  test "cannot list before acquired step is current (skip to sold is illegal)" do
    property = Property.create!(address: "3 Loop")
    assert_raises(Property::IllegalTransition) { property.sell! }
    assert_equal "acquired", property.reload.state
  end

  test "cannot mark under_offer before listing" do
    property = Property.create!(address: "4 Loop")
    assert_raises(Property::IllegalTransition) { property.mark_under_offer! }
  end

  test "cannot move backwards from sold" do
    property = Property.create!(address: "5 Loop", state: "sold")
    assert_raises(Property::IllegalTransition) { property.list! }
  end

  test "rejects unknown state" do
    assert_not Property.new(address: "6 Loop", state: "haunted").valid?
  end
end
