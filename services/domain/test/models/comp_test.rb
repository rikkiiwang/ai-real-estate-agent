require "test_helper"

class CompTest < ActiveSupport::TestCase
  test "valid with region, address, positive price and a sale date" do
    comp = Comp.new(region: "Mueller", address: "5 Sold St", sale_price: 612_000, sale_date: Date.new(2026, 3, 1))
    assert comp.valid?
  end

  test "requires a positive sale price" do
    assert_not Comp.new(region: "Mueller", address: "5 Sold St", sale_price: 0, sale_date: Date.today).valid?
  end

  test "requires a sale date" do
    assert_not Comp.new(region: "Mueller", address: "5 Sold St", sale_price: 600_000).valid?
  end

  test "stands alone by region without a property" do
    comp = Comp.create!(region: "Tarrytown", address: "9 Comp Ave", sale_price: 700_000, sale_date: Date.new(2026, 2, 1))
    assert_nil comp.property
    assert_includes Comp.in_region("Tarrytown"), comp
  end

  test "associates to a property when given" do
    property = Property.create!(address: "1 Anchor", state: "listed", list_price: 650_000, region: "Mueller")
    comp = Comp.create!(property: property, region: "Mueller", address: "2 Anchor", sale_price: 640_000, sale_date: Date.new(2026, 1, 15))
    assert_equal property, comp.property
    assert_includes property.comps, comp
  end
end
