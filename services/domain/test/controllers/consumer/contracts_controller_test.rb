require "test_helper"

class Consumer::ContractsControllerTest < ActionDispatch::IntegrationTest
  test "the contract page shows a read-only closing tracker (no broker buttons)" do
    lead = Lead.create!(side: "buyer", address: "9 Deal St", contact: "buyer@x.com", intent: "high")
    offer = Offer.create!(lead: lead, side: "buyer", status: "signed")
    contract = Contract.create!(offer: offer, form_id: "TREC-1-4", title: "Resale Contract",
                                form_json: "{}", source: "closer", status: "draft", delivered_at: Time.current)
    offer.closing_milestones.create!(milestone: "inspection_cleared", counterparty: "escrow",
                                     ping_status: "simulated", recorded_at: Time.current)

    post session_path, params: { name: "Buyer", email: "buyer@x.com" } # the contract's party
    get contract_path(contract)
    assert_response :success
    assert_select "#closing-tracker"
    assert_match(/Inspection cleared/i, @response.body)
    assert_match(/simulated in this demo/i, @response.body)
    assert_select "form[action=?]", record_milestone_broker_offer_path(offer), count: 0 # no broker button
  end
end
