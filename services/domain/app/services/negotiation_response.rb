# Automated negotiation within an authorized band (R: "negotiation within a
# price band"). A seller counters the platform's cash offer; the agent compares
# the counter to the authorized band — the opening cash offer (band_low) up to
# the valuation estimate (band_high, the most it may agree to WITHOUT a human) —
# and either accepts in-band or escalates above the ceiling. Every counter is
# recorded as a Negotiation (in or out of band); an out-of-band move enqueues a
# broker handoff rather than auto-negotiating past the authorization.
class NegotiationResponse
  Result = Struct.new(:within_band, :accepted, :counter, :open, :ceiling, :message, :negotiation, keyword_init: true)

  def self.counter(offer:, counter_amount:)
    blanks  = JSON.parse(offer.form_json.presence || "{}")
    open    = blanks["cash_offer"].to_i
    ceiling = blanks["valuation_estimate"].to_i
    counter = counter_amount.to_i

    negotiation = Negotiation.create!(
      offer: offer, counter_amount: counter,
      band_low: [open, 1].max, band_high: [ceiling, open, 1].max, note: "seller counter"
    )

    if negotiation.within_band?
      offer.update!(amount: counter)
      Result.new(
        within_band: true, accepted: true, counter: counter, open: open, ceiling: ceiling,
        message: "Done — I can meet #{money(counter)}. Your offer is updated and routed to a " \
                 "licensed broker for signature. Still not binding until the broker signs.",
        negotiation: negotiation
      )
    else
      EnqueueHandoff.call(
        lead: offer.lead, trigger: "high_dollar",
        reason: "seller counter #{money(counter)} above the authorized ceiling #{money(ceiling)}",
        recommended_action: "Broker to review the seller's counter above the authorized band"
      )
      Result.new(
        within_band: false, accepted: false, counter: counter, open: open, ceiling: ceiling,
        message: "That's above what I'm authorized to approve on my own (my ceiling is about " \
                 "#{money(ceiling)}). I've brought in a licensed broker to review your counter — " \
                 "they'll follow up.",
        negotiation: negotiation
      )
    end
  end

  def self.money(amount)
    ActiveSupport::NumberHelper.number_to_currency(amount, precision: 0)
  end
end
