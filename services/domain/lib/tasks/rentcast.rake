namespace :rentcast do
  desc "Import real Austin listings + market snapshots from RentCast (needs RENTCAST_API_KEY)"
  task import: :environment do
    client = RentCastClient.new
    unless client.configured?
      warn "RENTCAST_API_KEY not set — skipping RentCast import (marketplace keeps the curated sample)."
      next
    end
    # Override the curated ZIP set with ZIPS="78704,78745,..." if you want.
    zips = ENV["ZIPS"].to_s.split(",").map(&:strip).reject(&:empty?).presence
    result = RentCastImport.call(client: client, listing_limit: (ENV["LIMIT"] || 200).to_i, market_zips: zips)
    puts "RentCast: imported #{result.imported} real listings, #{result.snapshots} market snapshots, retired #{result.retired} stale listings."
  end

  desc "Pre-warm PropertyRecordCache for a bounded address set (caps RentCast calls). " \
       "ADDRESSES='a;b;c' MAX_CALLS=25"
  task prewarm: :environment do
    client = RentCastClient.new
    unless client.configured?
      warn "RENTCAST_API_KEY not set — skipping prewarm."
      next
    end
    addresses = ENV["ADDRESSES"].to_s.split(";").map(&:strip).reject(&:empty?)
    if addresses.empty?
      # Default: warm the browsable listing addresses missing a fresh record.
      addresses = Property.browsable.where(region: RentCastImport::DEFAULT_MARKET_ZIPS.map { |z| "Austin #{z}" })
                          .limit((ENV["MAX_CALLS"] || 25).to_i).pluck(:address)
    end
    result = PropertyRecordPrewarm.new(client: client)
                                  .call(addresses: addresses, max_calls: (ENV["MAX_CALLS"] || 25).to_i)
    puts "Prewarm: fetched #{result.fetched} (RentCast calls), " \
         "skipped #{result.skipped_fresh} fresh / #{result.skipped_budget} over-budget."
  end
end
