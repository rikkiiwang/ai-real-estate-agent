# Domain operation backing the gRPC Domain.CreateOffer RPC.
#
# Lands a drafted offer (from the Python Closer) in the broker-sign queue:
# creates the Offer and enqueues it via enqueue_for_broker! (status
# awaiting_broker, which also stamps the time-to-offer metric). A licensed human
# broker reviews and signs — the agent never signs. Callable directly so the
# domain logic is unit-tested independently of the transport.
class CreateOffer
  def self.call(lead:, side:, amount:, property_address: nil, form_json: nil)
    # Associate an existing property by address if one is already tracked; the
    # property lifecycle (acquire/list/sell) is owned elsewhere, so we never
    # create one here just to attach an offer.
    property = property_address.present? ? Property.find_by(address: property_address) : nil

    offer = Offer.create!(
      lead: lead,
      property: property,
      side: side,
      amount: amount,
      status: "drafting",
      form_json: form_json
    )
    offer.enqueue_for_broker! # -> awaiting_broker + time-to-offer metric
    offer
  end
end
