namespace :rentcast do
  desc "Import real Austin listings + market snapshots from RentCast (needs RENTCAST_API_KEY)"
  task import: :environment do
    client = RentCastClient.new
    unless client.configured?
      warn "RENTCAST_API_KEY not set — skipping RentCast import (marketplace keeps the curated sample)."
      next
    end
    result = RentCastImport.call(client: client, listing_limit: (ENV["LIMIT"] || 25).to_i)
    puts "RentCast: imported #{result.imported} real listings, #{result.snapshots} market snapshots."
  end
end
