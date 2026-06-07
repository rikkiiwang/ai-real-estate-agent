module Broker
  # Broker-facing review dashboard: the pending handoff queue and the offers
  # awaiting a licensed broker's signature. Thin controller — the queues live
  # as model scopes.
  class DashboardController < BaseController
    def show
      @handoffs = HandoffPacket.queue.includes(:lead)
      @offers = Offer.awaiting_broker_sign.includes(:lead, :property)
      @time_to_offer = OfferMetric.summary
      # Intent triaging lives on the visitor profile; surface ready leads here.
      @high_intent_buyers = Visitor.where("intent LIKE 'high%'").order(updated_at: :desc)
      # Requested showings awaiting a broker's confirm/decline (R6).
      @pending_showings = Appointment.pending.includes(:property, :lead)
    end
  end
end
