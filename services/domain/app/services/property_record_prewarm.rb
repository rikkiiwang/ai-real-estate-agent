# Pre-warms PropertyRecordCache from RentCast, off the request path. HARD-CAPPED
# by max_calls and CACHE-FIRST (skips rows still within TTL), so a refresh costs
# a bounded, logged number of RentCast requests — never per web request. This is
# the ONLY code that spends RentCast quota for valuation.
class PropertyRecordPrewarm
  Result = Struct.new(:fetched, :skipped_fresh, :skipped_budget, keyword_init: true)

  def initialize(client: RentCastClient.new)
    @client = client
  end

  def call(addresses:, max_calls: 25)
    fetched = skipped_fresh = skipped_budget = 0
    Array(addresses).each do |address|
      existing = PropertyRecordCache.find_by("lower(address) = ?", address.downcase)
      if existing&.fresh?
        skipped_fresh += 1
        next
      end
      if fetched >= max_calls
        skipped_budget += 1
        next
      end
      rec = @client.property_record(address: address)
      fetched += 1 # a call was spent even if the record is blank
      upsert(address, rec) if rec
    end
    Rails.logger.info("[prewarm] property records: fetched=#{fetched} (RentCast calls), " \
                      "skipped_fresh=#{skipped_fresh} skipped_budget=#{skipped_budget}")
    Result.new(fetched: fetched, skipped_fresh: skipped_fresh, skipped_budget: skipped_budget)
  end

  private

  def upsert(address, rec)
    cache = PropertyRecordCache.find_by("lower(address) = ?", address.downcase) || PropertyRecordCache.new(address: address)
    cache.assign_attributes(
      region: rec["zipCode"].present? ? "Austin #{rec["zipCode"]}" : cache.region,
      beds: rec["bedrooms"]&.to_i, baths: rec["bathrooms"], sqft: rec["squareFootage"]&.to_i,
      lot_sqft: rec["lotSize"], year_built: rec["yearBuilt"]&.to_i,
      lat: rec["latitude"], lng: rec["longitude"],
      tax_assessed_value: latest_assessment(rec),
      captured_at: Time.current,
    )
    cache.save!
  rescue ActiveRecord::RecordInvalid => e
    Rails.logger.warn("[prewarm] skipped #{address}: #{e.message}")
  end

  def latest_assessment(rec)
    assessments = rec["taxAssessments"]
    return nil unless assessments.is_a?(Hash) && assessments.any?
    year = assessments.keys.max_by(&:to_i)
    assessments.dig(year, "value")
  end
end
