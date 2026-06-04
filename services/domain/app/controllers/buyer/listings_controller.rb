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
      @market = MarketSnapshot.headline
    end

    def show
      @listing = Property.browsable.find(params[:id])
      @comps = Comp.in_region(@listing.region).recent_first.limit(3)
    end
  end
end
