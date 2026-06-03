module Buyer
  # The buyer offer journey: shows the cited decision bundle for a listing and
  # (in a later unit) submits the offer to the broker queue. Requires a
  # signed-in visitor.
  class OffersController < Consumer::BaseController
    def new
      @listing = Property.browsable.find(params[:listing_id])
      @bundle = decision_bundle_for(@listing)
    end

    # Records the buyer's offer in the broker-sign queue (awaiting_broker). The
    # offer is not binding until a licensed broker reviews and signs it. Reuses
    # the existing CreateLead/CreateOffer domain operations.
    def create
      @listing = Property.browsable.find(params[:listing_id])
      @bundle = decision_bundle_for(@listing)

      lead = CreateLead.call(side: "buyer", address: @listing.address, contact: current_visitor.email, intent: "high")
      @offer = CreateOffer.call(
        lead: lead,
        side: "buyer",
        amount: @bundle.offer_amount,
        property_address: @listing.address,
        form_json: offer_blanks.to_json
      )

      redirect_to buyer_listing_path(@listing),
        notice: "Your #{helpers.number_to_currency(@bundle.offer_amount, precision: 0)} offer is routed to a licensed broker for review — we'll confirm once it's approved. It isn't binding yet."
    end

    private

    def decision_bundle_for(listing)
      DecisionBundle.for(
        property: listing,
        offer_amount: params[:offer_amount],
        down_payment_pct: params[:down_payment_pct],
        term_years: params[:term_years]
      )
    end

    # The factual blanks captured at offer time (precursor to the TREC contract
    # draft generated on acceptance in a later unit). No authored clauses.
    def offer_blanks
      {
        property_address: @listing.address,
        buyer_name: current_visitor.name,
        buyer_email: current_visitor.email,
        offer_amount: @bundle.offer_amount,
        down_payment_pct: @bundle.down_payment_pct.to_i,
        loan_amount: @bundle.loan_amount,
        term_years: @bundle.term_years,
        mortgage_rate_pct: @bundle.mortgage_rate.value,
        estimated_monthly_payment: @bundle.monthly_payment
      }
    end
  end
end
