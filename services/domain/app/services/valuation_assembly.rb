# frozen_string_literal: true
# The single place that assembles a data-grounded valuation: resolve the
# subject's REAL attributes, pull comps from the cached pool, compute honest
# recency, and call the brain. Used by both the seller workspace and the buyer
# agent sidebar. Reads only the DB (zero RentCast). When the subject isn't in
# cache it falls back to the address-only path and flags low confidence rather
# than fabricating attributes.
class ValuationAssembly
  COMP_LIMIT = 6

  # Decorates the brain Result with a low-confidence flag for the fallback path.
  def self.low_conf(result, flag)
    result.define_singleton_method(:low_confidence?) { flag }
    result
  end

  def initialize(address:, client: BrainValuationClient.new)
    @address = address.to_s.strip
    @client = client
  end

  def call
    subject = SubjectResolver.new(address: @address).call
    return value_unknown if subject.nil?

    activity = MarketActivity.new(region: subject.region).call
    comps = CompsSelector.new(region: subject.region, exclude_address: subject.address,
                              subject_sqft: subject.sqft).call(limit: COMP_LIMIT)

    result = @client.valuation(
      address: subject.address,
      features: {
        beds: subject.beds, baths: subject.baths, sqft: subject.sqft,
        lot_sqft: subject.lot_sqft, year_built: subject.year_built,
        latitude: subject.latitude, longitude: subject.longitude,
        garage_spaces: subject.garage_spaces,
      },
      comps: comps,
      as_of: activity.as_of&.to_s,
      recent_activity: activity.summary,
    )
    self.class.low_conf(result, false)
  end

  private

  def value_unknown
    result = @client.valuation(address: @address)
    self.class.low_conf(result, true)
  end
end
