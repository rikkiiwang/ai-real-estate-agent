module Seller
  # Seller workspace: a seller requests a source-cited valuation and a platform
  # cash offer for their address. Reuses the brain's valuation + the existing
  # CreateLead/CreateOffer domain ops; never fabricates a number (insufficient
  # data routes to a broker follow-up instead of inventing a value). Requires a
  # signed-in visitor.
  class ValuationsController < Consumer::BaseController
    # The platform's preliminary cash offer as a fraction of the valuation
    # (an iBuyer convenience discount). Clearly labeled, broker-reviewed.
    CASH_OFFER_RATIO = 0.96

    def create
      @address = params[:address].to_s.strip
      return redirect_to(seller_home_path, alert: "Enter your home's address.") if @address.blank?

      @valuation = ValuationAssembly.new(address: @address, client: valuation_client).call

      if @valuation.usable?
        @cash_offer = (@valuation.estimate * CASH_OFFER_RATIO).round(-3).to_i
        persist_cash_offer!
      elsif @valuation.ok?
        # No fabrication: not enough data to value -> record the lead, no offer.
        CreateLead.call(side: "seller", address: @address, contact: current_visitor.email)
      end

      render :create
    end

    private

    def persist_cash_offer!
      lead = CreateLead.call(side: "seller", address: @address, contact: current_visitor.email, intent: "high")
      @offer = CreateOffer.call(
        lead: lead,
        side: "seller",
        amount: @cash_offer,
        property_address: @address,
        form_json: {
          property_address: @address,
          seller_name: current_visitor.name,
          seller_email: current_visitor.email,
          valuation_estimate: @valuation.estimate.to_i,
          cash_offer: @cash_offer
        }.to_json
      )
    end

    def valuation_client
      self.class.valuation_client_override&.call || BrainValuationClient.new
    end

    # Test seam.
    cattr_accessor :valuation_client_override
  end
end
