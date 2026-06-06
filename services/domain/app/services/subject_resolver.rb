# services/domain/app/services/subject_resolver.rb
# Resolves a subject address to its REAL attributes from cache so the AVM values
# a real home, not an address hash. Order: an existing Property listing, then the
# PropertyRecordCache (Part D), else nil (caller falls back to the honest hash
# path + lower confidence). Reads only the DB.
class SubjectResolver
  Subject = Struct.new(:address, :region, :beds, :baths, :sqft, :lot_sqft,
                       :year_built, :latitude, :longitude, :garage_spaces,
                       keyword_init: true)

  def initialize(address:)
    @address = address.to_s.strip
  end

  def call
    from_property || from_record_cache
  end

  private

  def from_property
    p = Property.where("lower(address) = ?", @address.downcase)
                .where(retired_at: nil)
                .first
    return nil unless p&.sqft.present?

    Subject.new(
      address: p.address, region: p.region, beds: p.beds.to_f, baths: p.baths.to_f,
      sqft: p.sqft.to_i, lot_sqft: nil, year_built: p.year_built,
      latitude: p.lat&.to_f, longitude: p.lng&.to_f, garage_spaces: nil,
    )
  end

  # Filled in Part D once PropertyRecordCache exists; nil-safe until then.
  def from_record_cache
    return nil unless defined?(PropertyRecordCache)
    rec = PropertyRecordCache.find_by("lower(address) = ?", @address.downcase)
    return nil unless rec&.sqft.present?

    Subject.new(
      address: rec.address, region: rec.region, beds: rec.beds.to_f, baths: rec.baths.to_f,
      sqft: rec.sqft.to_i, lot_sqft: rec.lot_sqft, year_built: rec.year_built,
      latitude: rec.lat&.to_f, longitude: rec.lng&.to_f, garage_spaces: rec.garage_spaces,
    )
  end
end
