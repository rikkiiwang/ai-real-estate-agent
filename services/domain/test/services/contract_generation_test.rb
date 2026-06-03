require "test_helper"

class ContractGenerationTest < ActiveSupport::TestCase
  def buyer_offer
    lead = Lead.create!(side: "buyer", address: "1 Mueller", contact: "jordan@example.com")
    Offer.create!(lead: lead, side: "buyer", amount: 625_000, status: "awaiting_broker",
      form_json: { property_address: "1 Mueller", buyer_name: "Jordan", buyer_email: "jordan@example.com" }.to_json)
  end

  class FakeCloser
    def initialize(result)
      @result = result
    end

    def generate_contract(**)
      @result
    end
  end

  def closer_drafted
    CloserClient::Result.new(drafted: true, form_id: "TREC-1-4", title: "TREC Resale",
      form_json: { "form_id" => "TREC-1-4", "title" => "TREC Resale",
        "blanks" => { "property_address" => "1 Mueller", "sales_price" => 625_000 } }.to_json, error: nil)
  end

  test "AE3: signing generates a blanks-only draft delivered to both parties (via Closer)" do
    offer = buyer_offer
    contract = ContractGeneration.call(offer, closer: FakeCloser.new(closer_drafted))

    assert_equal "draft", contract.status
    assert_equal "closer", contract.source
    assert contract.delivered_at.present?
    # R13: structurally no authored clause field.
    parsed = JSON.parse(contract.form_json)
    assert_not parsed.key?("clause")
    assert_not parsed.key?("clauses")
  end

  test "falls back to a Rails-filled draft when the Closer is unavailable" do
    offer = buyer_offer
    down = CloserClient::Result.new(drafted: false, error: "closer_unavailable")
    contract = ContractGeneration.call(offer, closer: FakeCloser.new(down))

    assert_equal "rails_fallback", contract.source
    assert_equal "draft", contract.status
    assert_equal "1 Mueller", contract.blanks["property_address"]
    assert_equal 625_000.0, contract.blanks["sales_price"]
  end

  test "is idempotent — a second call returns the existing contract" do
    offer = buyer_offer
    first = ContractGeneration.call(offer, closer: FakeCloser.new(closer_drafted))
    second = ContractGeneration.call(offer.reload, closer: FakeCloser.new(closer_drafted))
    assert_equal first.id, second.id
  end
end
