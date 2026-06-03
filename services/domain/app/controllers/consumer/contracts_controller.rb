module Consumer
  # A signed-in visitor's delivered contract drafts. Authorized by matching the
  # visitor's email to the offer's lead contact — a party only sees their own.
  class ContractsController < BaseController
    def index
      @contracts = visitor_contracts.order(delivered_at: :desc)
    end

    def show
      @contract = visitor_contracts.find(params[:id])
    end

    private

    def visitor_contracts
      Contract.joins(offer: :lead).where(leads: { contact: current_visitor.email })
    end
  end
end
