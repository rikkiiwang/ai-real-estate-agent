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

  test "rejects a non-positive list price" do
    assert_not Property.new(address: "7 Loop", list_price: 0).valid?
    assert_not Property.new(address: "7 Loop", list_price: -5).valid?
  end

  test "browsable returns only listed properties with a price" do
    listed_priced = Property.create!(address: "10 Mueller", state: "listed", list_price: 500_000)
    Property.create!(address: "11 Mueller", state: "listed") # listed, no price
    Property.create!(address: "12 Mueller", state: "acquired", list_price: 400_000) # priced, not listed

    assert_includes Property.browsable, listed_priced
    assert_equal 1, Property.browsable.count
  end

  test "region and price-range scopes filter inclusively" do
    a = Property.create!(address: "20 A", state: "listed", region: "Mueller", list_price: 600_000)
    b = Property.create!(address: "21 B", state: "listed", region: "Mueller", list_price: 800_000)
    Property.create!(address: "22 C", state: "listed", region: "Tarrytown", list_price: 650_000)

    in_mueller = Property.browsable.in_region("Mueller")
    assert_equal 2, in_mueller.count

    # Inclusive bounds: 600k and 800k both included at the exact edges.
    priced = Property.browsable.in_region("Mueller").priced_between(600_000, 800_000)
    assert_includes priced, a
    assert_includes priced, b
  end

  test "min_beds filters at the boundary" do
    three = Property.create!(address: "30 A", state: "listed", list_price: 500_000, beds: 3)
    Property.create!(address: "31 B", state: "listed", list_price: 500_000, beds: 2)
    assert_equal [three], Property.browsable.min_beds(3).to_a
  end
end
