# Pulls REAL Austin data from RentCast into the marketplace: active residential
# sale listings -> Property records, and per-ZIP sale-market stats -> cached
# MarketSnapshots. Idempotent (upsert by address / zip). Rate-limit friendly:
# one listings call + a few market calls per run — run on demand, not per
# request. RentCast does not license photos, so imported listings reuse the
# sample imagery (clearly labeled with their real RentCast provenance).
class RentCastImport
  # Verified, reachable sample photos (RentCast provides no images).
  PHOTOS = [
    "https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=900&q=70",
    "https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=900&q=70",
    "https://images.unsplash.com/photo-1576941089067-2de3c901e126?w=900&q=70",
    "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=900&q=70",
    "https://images.unsplash.com/photo-1605276374104-dee2a0ed3cd6?w=900&q=70",
    "https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=900&q=70"
  ].freeze

  SOURCE = "RentCast (live MLS data)".freeze
  MAX_MARKET_ZIPS = 5

  Result = Struct.new(:imported, :snapshots, keyword_init: true)

  def self.call(client: RentCastClient.new, listing_limit: 20)
    new(client).call(listing_limit: listing_limit)
  end

  def initialize(client)
    @client = client
  end

  def call(listing_limit: 20)
    return Result.new(imported: 0, snapshots: 0) unless @client.configured?

    rows = @client.sale_listings(limit: listing_limit).select { |r| residential?(r) }
    imported = rows.each_with_index.count { |row, i| upsert_listing(row, i) }

    zips = rows.map { |r| r["zipCode"] }.compact.uniq.first(MAX_MARKET_ZIPS)
    snapshots = zips.count { |zip| upsert_market(zip) }

    Result.new(imported: imported, snapshots: snapshots)
  end

  private

  def residential?(row)
    row["price"].to_i.positive? && row["bedrooms"] && row["bathrooms"] && row["squareFootage"].to_i.positive?
  end

  def upsert_listing(row, index)
    property = Property.find_or_initialize_by(address: row["formattedAddress"])
    property.assign_attributes(
      state: "listed",
      list_price: row["price"],
      beds: row["bedrooms"]&.to_i,
      baths: row["bathrooms"],
      sqft: row["squareFootage"]&.to_i,
      year_built: row["yearBuilt"]&.to_i,
      region: row["zipCode"].present? ? "Austin #{row["zipCode"]}" : "Austin",
      lat: row["latitude"],
      lng: row["longitude"],
      description: "Active #{row["propertyType"]} listing in Austin #{row["zipCode"]} — sourced live from RentCast.",
      photo_urls: [PHOTOS[index % PHOTOS.size], PHOTOS[(index + 2) % PHOTOS.size]],
      source_name: SOURCE,
      source_url: "https://www.rentcast.io",
      captured_at: Time.current
    )
    property.save!
  rescue ActiveRecord::RecordInvalid => e
    Rails.logger.warn("[rentcast] skipped #{row["formattedAddress"]}: #{e.message}")
    false
  end

  def upsert_market(zip)
    data = @client.market(zip: zip)
    return false unless data.is_a?(Hash) && data["medianPrice"]

    snapshot = MarketSnapshot.find_or_initialize_by(zip: zip)
    snapshot.assign_attributes(
      area: "Austin #{zip}",
      median_price: data["medianPrice"],
      avg_price_per_sqft: data["averagePricePerSquareFoot"],
      total_listings: data["totalListings"],
      new_listings: data["newListings"],
      avg_days_on_market: data["averageDaysOnMarket"],
      as_of: (Date.parse(data["lastUpdatedDate"]) rescue Date.current),
      source: "RentCast"
    )
    snapshot.save!
  end
end
