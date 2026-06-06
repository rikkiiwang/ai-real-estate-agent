# services/domain/app/services/comps_selector.rb
# Picks comparable ACTIVE listings for a subject from the cached Property pool.
# Reads only the DB (never RentCast). Comps are asking-price active listings —
# the brain labels them as such, never as closed sales. Ranked by similarity
# (price-per-sqft proximity is handled downstream by recency weighting; here we
# pick the freshest, closest-in-size same-region listings).
class CompsSelector
  Comp = Struct.new(:id, :address, :price, :sqft, :beds, :baths, :distance_mi,
                    :age_days, keyword_init: true)

  def initialize(region:, exclude_address: nil, subject_sqft: nil)
    @region = region
    @exclude_address = exclude_address.to_s.strip.downcase
    @subject_sqft = subject_sqft
  end

  def call(limit: 5)
    scope = Property.browsable.where(region: @region).where.not(sqft: nil)
    rows = scope.reject { |p| p.address.to_s.strip.downcase == @exclude_address }
    rows = rows.sort_by { |p| size_gap(p) }.first(limit)
    rows.map { |p| to_comp(p) }
  end

  private

  def size_gap(property)
    return 0 if @subject_sqft.blank? || property.sqft.blank?
    (property.sqft - @subject_sqft).abs
  end

  def to_comp(property)
    Comp.new(
      id: property.id.to_s,
      address: property.address,
      price: property.list_price.to_f,
      sqft: property.sqft.to_i,
      beds: property.beds.to_i,
      baths: property.baths.to_f,
      distance_mi: 0.0, # same-region proxy; refined when subject geo is known
      age_days: age_days_for(property),
    )
  end

  def age_days_for(property)
    return 0 if property.captured_at.blank?
    ((Time.current - property.captured_at) / 1.day).floor
  end
end
