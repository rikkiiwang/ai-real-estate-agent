require "net/http"
require "json"

# Thin client for the RentCast API (real Austin sale listings + market stats).
# Reads RENTCAST_API_KEY from the env; `configured?` is false without it, so the
# marketplace falls back to its curated sample. Free tier is rate-limited (~50
# calls/month), so callers must CACHE — never call this per web request.
class RentCastClient
  BASE = "https://api.rentcast.io/v1".freeze

  def initialize(api_key: ENV["RENTCAST_API_KEY"])
    @api_key = api_key.presence
  end

  def configured?
    @api_key.present?
  end

  # Active sale listings (defaults to residential single-family in Austin).
  # All residential types by default (Single Family, Condo, Townhouse, …) — pass
  # property_type to narrow. One request returns up to `limit` listings, so a
  # bigger limit costs the SAME single API call (the import then caches them).
  def sale_listings(city: "Austin", state: "TX", limit: 200, property_type: nil)
    params = { city: city, state: state, status: "Active", limit: limit }
    params[:propertyType] = property_type if property_type.present?
    get("/listings/sale", **params) || []
  end

  # Aggregate sale-market stats for a ZIP (median price, $/sqft, DOM, as-of date).
  def market(zip:)
    body = get("/markets", zipCode: zip, dataType: "Sale")
    body.is_a?(Hash) ? (body["saleData"] || body) : nil
  end

  # A single property's record (real attributes + tax assessment) for one
  # address. ONE request per address — callers MUST cache (PropertyRecordCache).
  # Returns the first matching record hash, or nil.
  def property_record(address:)
    body = get("/properties", address: address)
    rec = body.is_a?(Array) ? body.first : body
    rec.is_a?(Hash) ? rec : nil
  end

  private

  def get(path, **params)
    return nil unless configured?

    uri = URI("#{BASE}#{path}")
    uri.query = URI.encode_www_form(params)
    req = Net::HTTP::Get.new(uri)
    req["X-Api-Key"] = @api_key
    req["Accept"] = "application/json"

    res = Net::HTTP.start(uri.host, uri.port, use_ssl: true, open_timeout: 8, read_timeout: 20) do |http|
      http.request(req)
    end
    return JSON.parse(res.body) if res.is_a?(Net::HTTPSuccess)

    Rails.logger.warn("[rentcast] #{path} -> HTTP #{res.code}")
    nil
  rescue StandardError => e
    Rails.logger.warn("[rentcast] #{path} failed: #{e.class}: #{e.message}")
    nil
  end
end
