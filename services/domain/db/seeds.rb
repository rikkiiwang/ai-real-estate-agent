# Seeds the consumer marketplace with a curated static sample of Austin
# listings + nearby-sale comps. Idempotent: re-running upserts by address.
# This is sample data captured once (not a live feed); provenance is labeled.

require "yaml"

data_path = Rails.root.join("db/seed_data/austin_listings.yml")
data = YAML.load_file(data_path, aliases: true)

photos          = data.fetch("photos")
listings        = data.fetch("listings")
comps_by_region = data.fetch("comps", {})

captured_at = Time.current
source_name = "Curated Austin sample (Unsplash imagery)"
source_url  = "https://unsplash.com"

listings.each_with_index do |row, i|
  property = Property.find_or_initialize_by(address: row.fetch("address"))
  # Two cycled sample photos per listing so the gallery always renders.
  listing_photos = [photos[i % photos.size], photos[(i + 3) % photos.size]]

  property.assign_attributes(
    state: "listed",
    list_price: row.fetch("list_price"),
    beds: row["beds"],
    baths: row["baths"],
    sqft: row["sqft"],
    region: row["region"],
    year_built: row["year_built"],
    description: row["description"],
    photo_urls: listing_photos,
    source_name: source_name,
    source_url: source_url,
    captured_at: captured_at
  )
  property.save!
end

comps_by_region.each do |region, rows|
  rows.each do |row|
    comp = Comp.find_or_initialize_by(region: region, address: row.fetch("address"))
    comp.assign_attributes(
      sale_price: row.fetch("sale_price"),
      sale_date: row.fetch("sale_date"),
      distance_mi: row["distance_mi"],
      source_name: "Travis County / TCAD recorded sales (sample)",
      source_url: "https://traviscad.org"
    )
    comp.save!
  end
end

puts "Seeded #{Property.browsable.count} browsable listings and #{Comp.count} comps."
