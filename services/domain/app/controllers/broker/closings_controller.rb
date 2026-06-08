module Broker
  # Broker records a closing milestone on a signed deal; the orchestrator routes
  # the counterparty ping (R10). Behind require_broker.
  class ClosingsController < BaseController
    def create
      offer = Offer.find(params[:id])
      result = ClosingOrchestration.record(offer: offer, milestone: params[:milestone])
      if result.recorded?
        redirect_to broker_dashboard_path,
          notice: "#{result.milestone.humanize} recorded — #{result.counterparty} notified (#{result.ping_status})."
      else
        redirect_to broker_dashboard_path,
          alert: "Could not record #{params[:milestone]}: #{result.reason}."
      end
    end
  end
end
