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
    puts "RentCast: imported #{result.imported} real listings, #{result.snapshots} market snapshots."
  end
end
