require "test_helper"

# Smoke test for the marketplace seed data + static market config. Runs the
# seed script against the test DB and asserts the curated sample is coherent
# and fully provenance-labeled.
class SeedsTest < ActiveSupport::TestCase
  def setup
    Comp.delete_all
    Offer.delete_all
    Property.delete_all
    load Rails.root.join("db/seeds.rb")
  end

  test "seeds ~20 browsable listings with price, photos, region and provenance" do
    listings = Property.browsable
    assert_operator listings.count, :>=, 18, "expected a full sample of listings"

    listings.find_each do |p|
      assert p.list_price.to_f.positive?, "#{p.address} missing price"
      assert p.region.present?, "#{p.address} missing region"
      assert p.photo_urls.present? && p.photo_urls.any?, "#{p.address} missing photos"
      assert p.source_name.present? && p.captured_at.present?, "#{p.address} missing provenance"
    end
  end

  test "seeds comps with provenance" do
    assert_operator Comp.count, :>=, 10
    Comp.find_each do |c|
      assert c.sale_price.to_f.positive?
      assert c.sale_date.present?
      assert c.source_name.present?
    end
  end

  test "is idempotent (re-running does not duplicate)" do
    count = Property.browsable.count
    load Rails.root.join("db/seeds.rb")
    assert_equal count, Property.browsable.count
  end

  test "marketplace config carries a value, source and as_of for rate and tax" do
    cfg = Rails.application.config_for(:marketplace)
    %i[mortgage_rate property_tax_rate].each do |key|
      entry = cfg.fetch(key)
      assert entry[:value].to_f.positive?, "#{key} missing value"
      assert entry[:source].present?, "#{key} missing source"
      assert entry[:as_of].present?, "#{key} missing as_of"
    end
  end
end
