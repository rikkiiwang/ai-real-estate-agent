require "realestate/v1/realestate_services_pb"

# gRPC handler implementing the shared realestate.v1.Domain service.
#
# Thin transport adapter: it translates protobuf messages to/from the domain
# service objects (CreateLead, EnqueueHandoff), which hold the actual logic and
# are tested independently. Bind this into a GRPC::RpcServer to expose the two
# RPCs over the wire (see lib/tasks or a runner); the handler + service objects
# are fully tested here without standing up a socket.
class DomainServer < Realestate::V1::Domain::Service
  def create_lead(request, _call = nil)
    lead = CreateLead.call(
      side: request.side,
      address: request.address,
      contact: request.contact
    )

    Realestate::V1::Lead.new(
      id: lead.id.to_s,
      side: lead.side,
      address: lead.address,
      intent: lead.intent
    )
  end

  def enqueue_handoff(request, _call = nil)
    lead = Lead.find(request.lead_id)

    packet = EnqueueHandoff.call(
      lead: lead,
      trigger: request.trigger,
      confidence: request.confidence,
      reason: request.reason,
      transcript: request.transcript,
      recommended_action: request.recommended_action
    )

    Realestate::V1::EnqueueHandoffResponse.new(handoff_id: packet.id.to_s)
  end

  def create_offer(request, _call = nil)
    lead = Lead.find(request.lead_id)

    offer = CreateOffer.call(
      lead: lead,
      side: request.side,
      amount: request.amount,
      property_address: request.property_address,
      form_json: request.form_json
    )

    Realestate::V1::Offer.new(
      id: offer.id.to_s,
      lead_id: offer.lead_id.to_s,
      side: offer.side,
      amount: offer.amount.to_f,
      status: offer.status
    )
  end
end
