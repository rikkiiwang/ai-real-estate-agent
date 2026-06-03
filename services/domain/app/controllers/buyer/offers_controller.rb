module Buyer
  # The buyer offer journey: shows the cited decision bundle for a listing and
  # (in a later unit) submits the offer to the broker queue. Requires a
  # signed-in visitor.
  class OffersController < Consumer::BaseController
    def new
      @listing = Property.browsable.find(params[:listing_id])
      @bundle = DecisionBundle.for(
        property: @listing,
        offer_amount: params[:offer_amount],
        down_payment_pct: params[:down_payment_pct],
        term_years: params[:term_years]
      )
    end
  end
end
