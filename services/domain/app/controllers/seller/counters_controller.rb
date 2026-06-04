module Seller
  # Handles a seller's counter to the platform cash offer. Scoped to the
  # visitor's own offer (via the lead's email), so one seller can't counter
  # another's. The band check + record + escalation live in NegotiationResponse.
  class CountersController < Consumer::BaseController
    def create
      @offer = Offer.joins(:lead)
        .where(leads: { contact: current_visitor.email }, side: "seller")
        .find(params[:offer_id])
      @result = NegotiationResponse.counter(offer: @offer, counter_amount: params[:counter_amount])
    end
  end
end
