module Broker
  # Broker action: sign an awaiting-broker offer. Signing is the human gate the
  # agent never crosses — and the moment a TREC contract draft is generated and
  # delivered in-app to both parties.
  class OffersController < BaseController
    def sign
      offer = Offer.find(params[:id])
      offer.sign!
      contract = ContractGeneration.call(offer)
      notice = if contract
                 "Offer signed and a contract draft was delivered to both parties."
               else
                 "Offer signed. The contract needs broker/legal follow-up before it can be drafted."
               end
      redirect_to broker_dashboard_path, notice: notice
    end
  end
end
