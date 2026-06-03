# Parses a natural-language sidebar message into listing-search filters
# ("3-bed homes under $700k in Mueller" -> region/beds/price_max). Pragmatic and
# Rails-side by design: search stays fast and reliable, while the brain handles
# grounded Q&A. Records dimensions it could not parse rather than dropping them
# silently.
class SearchIntent
  SEARCH_HINTS = /\b(show|find|search|browse|look(ing)?|homes?|houses?|listings?|under|below|over|above|in|near|bed|bedroom|bd|condo|place)\b/i

  Parsed = Struct.new(:region, :price_min, :price_max, :beds, :ignored, keyword_init: true) do
    def to_search_params = { region: region, price_min: price_min, price_max: price_max, beds: beds }

    def any_filter? = [region, price_min, price_max, beds].any?(&:present?)

    def summary
      parts = []
      parts << "#{beds}+ bed" if beds
      parts << "under #{ActiveSupport::NumberHelper.number_to_currency(price_max, precision: 0)}" if price_max
      parts << "over #{ActiveSupport::NumberHelper.number_to_currency(price_min, precision: 0)}" if price_min
      parts << "in #{region}" if region
      parts.join(" ").presence || "your filters"
    end
  end

  def self.detect(text, regions: nil)
    new(text, regions: regions).detect
  end

  def initialize(text, regions: nil)
    @text = text.to_s
    @regions = regions || ListingSearch.regions
  end

  # Returns a Parsed when the message reads like a browse request, else nil.
  def detect
    return nil unless @text.match?(SEARCH_HINTS)

    parsed = Parsed.new(
      region: parse_region,
      price_min: parse_price(:min),
      price_max: parse_price(:max),
      beds: parse_beds,
      ignored: []
    )
    parsed.ignored = ignored_dimensions(parsed)
    parsed.any_filter? ? parsed : nil
  end

  private

  def parse_region
    @regions.find { |r| @text.downcase.include?(r.downcase) }
  end

  def parse_beds
    if (m = @text.match(/(\d+)\s*[-\s]?\s*(?:\+|or more)?\s*(?:bed|bedroom|bd|br)\b/i))
      m[1].to_i
    end
  end

  # Parses the price token that FOLLOWS the bound keyword, so "over $400k under
  # $800k" yields price_min=400k and price_max=800k (not both = the largest
  # number), and unrelated numbers like street addresses aren't mistaken for a
  # bound. Numbers like "$700k", "700k", "1.2m", "650,000".
  def parse_price(bound)
    keyword = bound == :max ? /(?:under|below|less than|up to|max|<=?)/i : /(?:over|above|more than|at least|min|>=?)/i
    m = @text.match(/#{keyword}\s*\$?\s?(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)/i)
    return nil unless m

    value = to_amount(m[1], m[2])
    value if value && value > 1000
  end

  def to_amount(num, unit)
    base = num.delete(",").to_f
    case unit.downcase
    when "k" then (base * 1_000).to_i
    when "m" then (base * 1_000_000).to_i
    else base.to_i
    end
  end

  def ignored_dimensions(parsed)
    ignored = []
    ignored << "region" if mentions_region_word? && parsed.region.nil?
    ignored
  end

  def mentions_region_word?
    @text.match?(/\b(?:in|near|around)\s+[a-z]/i)
  end
end
