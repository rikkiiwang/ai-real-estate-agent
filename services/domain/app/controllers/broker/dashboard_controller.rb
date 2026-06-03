module Broker
  # Broker-facing review dashboard: the pending handoff queue and the offers
  # awaiting a licensed broker's signature. Thin controller — the queues live
  # as model scopes.
  class DashboardController < BaseController
    def show
      @handoffs = HandoffPacket.queue.includes(:lead)
      @offers = Offer.awaiting_broker_sign.includes(:lead, :property)
      @time_to_offer = OfferMetric.summary
    end
  end
end
