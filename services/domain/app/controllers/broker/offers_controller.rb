module Broker
  # Broker action: sign an awaiting-broker offer. Signing is the human gate the
  # agent never crosses — and the moment a TREC contract draft is generated and
  # delivered in-app to both parties.
  class OffersController < BaseController
    def sign
      offer = Offer.find(params[:id])
      offer.sign!
      ContractGeneration.call(offer)
      redirect_to broker_dashboard_path, notice: "Offer signed and a contract draft was delivered to both parties."
    end
  end
end
