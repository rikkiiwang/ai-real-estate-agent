# Pulls REAL Austin data from RentCast into the marketplace: active residential
# sale listings -> Property records, and per-ZIP sale-market stats -> cached
# MarketSnapshots. Idempotent (upsert by address / zip). Rate-limit friendly:
# one listings call + a few market calls per run — run on demand, not per
# request. RentCast does not license photos, so imported listings reuse the
# sample imagery (clearly labeled with their real RentCast provenance).
class RentCastImport
  # Verified, reachable sample photos (RentCast provides no images). A dozen so a
  # large import doesn't repeat the same handful of pictures across every card.
  PHOTOS = [
    "https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=900&q=70",
    "https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=900&q=70",
    "https://images.unsplash.com/photo-1576941089067-2de3c901e126?w=900&q=70",
    "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=900&q=70",
    "https://images.unsplash.com/photo-1605276374104-dee2a0ed3cd6?w=900&q=70",
    "https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=900&q=70",
    "https://images.unsplash.com/photo-1583608205776-bfd35f0d9f83?w=900&q=70",
    "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=900&q=70",
    "https://images.unsplash.com/photo-1599809275671-b5942cabc7a2?w=900&q=70",
    "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=900&q=70",
    "https://images.unsplash.com/photo-1572120360610-d971b9d7767c?w=900&q=70"
  ].freeze

  SOURCE = "RentCast (live listing data)".freeze

  # A curated set of well-known Austin ZIPs to snapshot for the market banner.
  # We snapshot a CHOSEN list (not whatever ZIPs happen to appear in the listing
  # batch) so the banner's ZIP picker is predictable and covers recognisable
  # areas — Mueller (78723), South Congress/Zilker (78704), East Austin (78702),
  # Tarrytown (78703), Northwest Hills (78731), Hyde Park (78751), etc.
  DEFAULT_MARKET_ZIPS = %w[
    78702 78703 78704 78723 78731 78744 78745 78746 78751 78759
  ].freeze
  MAX_MARKET_ZIPS = 12

  Result = Struct.new(:imported, :snapshots, :retired, keyword_init: true)

  def self.call(client: RentCastClient.new, listing_limit: 200, market_zips: nil)
    new(client).call(listing_limit: listing_limit, market_zips: market_zips)
  end

  def initialize(client)
    @client = client
  end

  def call(listing_limit: 200, market_zips: nil)
    return Result.new(imported: 0, snapshots: 0, retired: 0) unless @client.configured?

    run_at = Time.current
    prior_active = rentcast_active.count

    rows = @client.sale_listings(limit: listing_limit).select { |r| residential?(r) }
    imported = rows.each_with_index.count { |row, i| upsert_listing(row, i, run_at) }

    # Snapshot the curated ZIPs first, then any extra ZIPs the listings surfaced,
    # deduped and capped. A ZIP with no market data is simply skipped.
    listing_zips = rows.map { |r| r["zipCode"] }.compact
    zips = (Array(market_zips.presence || DEFAULT_MARKET_ZIPS) + listing_zips).uniq.first(MAX_MARKET_ZIPS)
    snapshots = zips.count { |zip| upsert_market(zip) }

    retired = retire_stale(run_at, prior_active, imported)

    Result.new(imported: imported, snapshots: snapshots, retired: retired)
  end

  private

  def rentcast_active
    Property.where("source_name LIKE ?", "RentCast%").where(retired_at: nil)
  end

  def residential?(row)
    row["price"].to_i.positive? && row["bedrooms"] && row["bathrooms"] && row["squareFootage"].to_i.positive?
  end

  # Retire RentCast listings that were NOT refreshed this run (i.e. they dropped
  # out of the active feed — sold or delisted), so they stop being browsable and
  # labelled "Live listing". Guarded against a thin/transient feed: if this run
  # refreshed fewer than half of what was active, skip retirement rather than
  # wipe the catalog on an API hiccup.
  def retire_stale(run_at, prior_active, imported)
    return 0 if prior_active.positive? && imported < prior_active / 2

    rentcast_active.where("captured_at < ?", run_at)
                   .update_all(retired_at: Time.current, updated_at: Time.current)
  end

  def upsert_listing(row, index, run_at)
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
      captured_at: run_at,
      retired_at: nil # a listing that reappears in the feed is reactivated
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
