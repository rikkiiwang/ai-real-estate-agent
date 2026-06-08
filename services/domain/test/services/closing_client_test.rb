require "test_helper"

class ClosingClientTest < ActiveSupport::TestCase
  # A fake gRPC stub recording the request and returning a canned response.
  class FakeStub
    Resp = Struct.new(:pinged, :counterparty, :message, keyword_init: true)
    attr_reader :last
    def record_milestone(req)
      @last = req
      Resp.new(pinged: true, counterparty: "escrow", message: "Notified escrow: ... for #{req.deal_id}.")
    end
  end

  test "maps the brain response into a Result" do
    stub = FakeStub.new
    res = ClosingClient.new(stub: stub).record_milestone(deal_id: "deal-3", milestone: "earnest_deposited")
    assert res.ok?
    assert res.pinged
    assert_equal "escrow", res.counterparty
    assert_equal "deal-3", stub.last.deal_id
    assert_equal "earnest_deposited", stub.last.milestone
  end

  test "a transport error degrades to an error Result, not a raise" do
    raising = Object.new
    def raising.record_milestone(_req) = raise(GRPC::Unavailable.new("down"))
    res = ClosingClient.new(stub: raising).record_milestone(deal_id: "deal-3", milestone: "funded")
    assert_not res.ok?
    assert_equal "closing_unavailable", res.error
  end
end
