# services/domain/app/services/market_activity.rb
# Computes an HONEST freshness label + recent-activity summary for a region from
# the cached MarketSnapshot (per-ZIP RentCast sale stats). No fabricated live
# stream: when there's no snapshot it says so. Reads only the DB.
class MarketActivity
  Result = Struct.new(:as_of, :summary, keyword_init: true)

  def initialize(region:)
    @region = region
    @zip = region.to_s[/\d{5}/]
  end

  def call
    snap = @zip && MarketSnapshot.find_by(zip: @zip)
    return Result.new(as_of: nil, summary: "No recent market data for this area.") unless snap

    parts = []
    parts << "#{snap.new_listings} new listing#{'s' unless snap.new_listings == 1} recently" if snap.new_listings.present?
    parts << "median list $#{ActiveSupport::NumberHelper.number_to_delimited(snap.median_price.to_i)}" if snap.median_price.present?
    parts << "avg #{snap.avg_days_on_market.to_i} days on market" if snap.avg_days_on_market.present?
    summary = parts.any? ? parts.join(" · ") : "Market snapshot available."
    Result.new(as_of: snap.as_of, summary: summary)
  end
end
