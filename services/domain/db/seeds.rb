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

# A demo Concierge conversation that spans Chat -> SMS -> Voice -> Email and ends
# high-intent, so the console and the broker queue have content out of the box.
demo_contact = "demo-buyer@example.com"
unless Conversation.exists?(contact: demo_contact)
  convo = Conversation.create!(side: "buyer", contact: demo_contact, name: "Dana Demo")
  ConciergeService.ingest(conversation: convo, channel: "chat",  body: "Just browsing a few neighborhoods.")
  ConciergeService.ingest(conversation: convo, channel: "sms",   body: "Texting now — still looking around.")
  # A grounded turn: an address in the signals lets the agent reply with cited specifics.
  ConciergeService.ingest(conversation: convo, channel: "voice", body: "Is 6705 Manchaca Rd fairly priced?",
                          signals: { "address" => "6705 Manchaca Rd, Austin, TX 78745" })
  ConciergeService.ingest(conversation: convo, channel: "email", body: "We're pre-approved and need to move in 3 weeks.",
                          signals: { "preapproval" => "true", "move_timeline_days" => "21" })
  puts "Seeded a demo Concierge conversation (#{convo.channels_used.join(' -> ')}, intent=#{convo.reload.intent})."
end
