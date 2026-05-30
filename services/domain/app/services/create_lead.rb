# Domain operation backing the gRPC Domain.CreateLead RPC.
#
# Wired to the gRPC handler in DomainServer; also callable directly so the
# domain logic is unit-tested independently of the transport.
class CreateLead
  def self.call(side:, address:, contact: nil, intent: "unknown")
    Lead.create!(side: side, address: address, contact: contact, intent: intent)
  end
end
