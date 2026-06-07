# Seeds clearly-labeled SAMPLE cross-source data so the R1 cross-source check +
# neighborhood pulse are visible offline (without a RentCast key): one market
# snapshot per seeded region (derived from that region's listings) and one tax
# assessment per listing. Idempotent (upsert by area / address). The real
# `rake rentcast:import` / `rentcast:prewarm` path overwrites these with live data.
#
# This is demo data, labeled "(sample)" exactly like the curated listings/comps —
# never presented as live. Reconciliation cites each with its source + "as of".
module SampleCrossSourceSeed
  MARKET_SOURCE = "Curated Austin sample".freeze

  module_function

  def call(properties: Property.browsable)
    props = properties.to_a
    markets = seed_market(props)
    taxes = seed_tax(props)
    [markets, taxes]
  end

  # One snapshot per ZIP (the same natural key the real rentcast:import uses, so a
  # later import merges cleanly — and several neighborhoods can share a ZIP).
  # Median price + $/sqft derived from that ZIP's own listings. Listings whose
  # address carries no ZIP are skipped (the pulse needs a market key).
  def seed_market(props)
    count = 0
    props.group_by { |p| zip_of(p) }.each do |zip, group|
      next if zip.blank?

      priced = group.select { |p| p.list_price.present? && p.sqft.to_i.positive? }
      next if priced.empty?

      snap = MarketSnapshot.find_or_initialize_by(zip: zip)
      snap.assign_attributes(
        area: group.first.region,
        median_price: median_of(priced.map { |p| p.list_price.to_i }),
        avg_price_per_sqft: median_of(priced.map { |p| (p.list_price.to_f / p.sqft).round }),
        avg_days_on_market: 21,
        new_listings: group.size,
        total_listings: group.size,
        as_of: Date.current,
        source: MARKET_SOURCE
      )
      snap.save!
      count += 1
    end
    count
  end

  # One tax assessment per listing, deterministically varied (~80–95% of asking)
  # so the asking-vs-assessment delta is meaningful and stable across re-seeds.
  def seed_tax(props)
    count = 0
    props.each do |p|
      next unless p.list_price.present? && p.sqft.to_i.positive?

      rec = PropertyRecordCache.find_or_initialize_by(address: p.address)
      factor = 0.80 + (stable_hash(p.address) % 16) / 100.0 # 0.80..0.95
      rec.assign_attributes(
        region: p.region, beds: p.beds, baths: p.baths, sqft: p.sqft,
        year_built: p.year_built, lat: p.lat, lng: p.lng,
        tax_assessed_value: (p.list_price.to_i * factor).round,
        captured_at: Time.current
      )
      rec.save!
      count += 1
    end
    count
  end

  def zip_of(property)
    property.address.to_s[/\b(\d{5})\b/, 1]
  end

  def median_of(values)
    sorted = values.sort
    sorted[sorted.size / 2]
  end

  # Deterministic, dependency-free hash (stable across runs, no randomness).
  def stable_hash(str)
    str.to_s.bytes.sum
  end
end
