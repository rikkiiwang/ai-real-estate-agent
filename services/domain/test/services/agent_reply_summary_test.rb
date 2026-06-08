require "test_helper"

class AgentReplySummaryTest < ActiveSupport::TestCase
  Msg = Struct.new(:message)

  test "uses the orchestrator message verbatim when present" do
    assert_equal "It's competitively priced.",
      AgentReplySummary.line(result: Msg.new("It's competitively priced."), query: "is it a deal?")
  end

  test "summarizes card answers in one line" do
    assert_match(/price check/i, AgentReplySummary.line(price_check: true, address: "9 Demo St", query: "priced well?"))
    assert_match(/neighborhood/i, AgentReplySummary.line(insight_key: "neighborhood", query: "area?"))
    assert_match(/photos/i, AgentReplySummary.line(insight_key: "photos", query: "photos?"))
    assert_match(/tour/i, AgentReplySummary.line(showing: true, query: "tour?"))
    assert_match(/listings/i, AgentReplySummary.line(listings: [1, 2], query: "3 bed homes"))
  end

  test "falls back to echoing the question" do
    assert_equal "Answered: tell me about schools", AgentReplySummary.line(query: "tell me about schools")
  end
end
