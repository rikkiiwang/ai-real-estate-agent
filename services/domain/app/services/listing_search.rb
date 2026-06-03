# Encapsulates the browsable-listing filter query (region, price range, beds).
# Pure query object so both the catalog UI (U3) and the agent-driven search
# (U6) share one definition of "what the buyer can see".
class ListingSearch
  attr_reader :region, :price_min, :price_max, :beds

  def initialize(region: nil, price_min: nil, price_max: nil, beds: nil)
    @region    = region.presence
    @price_min = presence_int(price_min)
    @price_max = presence_int(price_max)
    @beds      = presence_int(beds)
  end

  # Build from controller params or an agent-parsed intent hash.
  def self.from_params(params)
    new(
      region: params[:region],
      price_min: params[:price_min],
      price_max: params[:price_max],
      beds: params[:beds]
    )
  end

  def results
    Property
      .browsable
      .in_region(region)
      .priced_between(price_min, price_max)
      .min_beds(beds)
      .order(:list_price)
  end

  # Distinct regions that currently have browsable listings, for the filter UI.
  def self.regions
    Property.browsable.distinct.order(:region).pluck(:region).compact
  end

  # True when any filter is active (used to show a "clear filters" affordance).
  def filtered?
    region.present? || price_min.present? || price_max.present? || beds.present?
  end

  def to_h
    { region: region, price_min: price_min, price_max: price_max, beds: beds }
  end

  private

  def presence_int(value)
    return nil if value.nil? || value.to_s.strip.empty?

    Integer(value.to_s.gsub(/[,_$\s]/, ""))
  rescue ArgumentError
    nil
  end
end
