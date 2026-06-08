module Buyer
  # Public, browsable listing catalog — the consumer front door. No login
  # required to browse, filter, and compare (R1, R2). Inherits ApplicationController
  # directly so it is NOT behind broker auth.
  class ListingsController < ApplicationController
    layout "marketplace"

    def index
      @search = ListingSearch.from_params(params)
      @listings = @search.results
      @regions = ListingSearch.regions
      # Market banner: the picked ZIP, else the most-recent snapshot.
      @market_zips = MarketSnapshot.order(:zip).pluck(:zip)
      @market = MarketSnapshot.find_by(zip: params[:zip]) || MarketSnapshot.headline
    end

    def show
      @listing = Property.browsable.find(params[:id])
      # Real, collision-aware showing slots for the request form (R6).
      @showings = ShowingScheduler.available_slots(property: @listing, now: Time.current)
      # Listing analysis (neighborhood / photos / price / comps) is now answered on
      # demand through Ask Atlas, not stacked on the page.
    end
  end
end
