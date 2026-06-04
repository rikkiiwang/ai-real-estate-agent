require "test_helper"

class Agent::MessagesControllerTest < ActionDispatch::IntegrationTest
  # A fake brain client returning a preset Result; records the call args so we
  # can assert context resolution.
  class FakeClient
    attr_reader :last_args

    def initialize(result)
      @result = result
    end

    def orchestrate(**args)
      @last_args = args
      @result
    end
  end

  def use_client(fake)
    Agent::MessagesController.client_factory = -> { fake }
    yield
  ensure
    Agent::MessagesController.client_factory = nil
  end

  def grounded
    BrainConversationClient::Result.new(
      outcome: "send", escalated: false, message: "It's competitively priced.",
      confidence: 0.8, coverage: 0.9, agreement: 0.8, self_consistency: 0.7,
      claims: [BrainConversationClient::Claim.new(claim: "Comps near $610k", label: "entailed",
        score: 0.9, source_kind: "comparable_sale", supported: true)],
      steps: [], error: nil
    )
  end

  test "posting a question renders the question and a cited reply" do
    use_client(FakeClient.new(grounded)) do
      post agent_messages_path, params: { query: "Is this priced well?" }, as: :turbo_stream
    end
    assert_response :success
    assert_match "Is this priced well?", @response.body
    assert_match "competitively priced", @response.body
    assert_match "comparable sale", @response.body # friendly source label
  end

  test "a listing_id pins the question to that property's address (context-aware)" do
    listing = Property.create!(address: "500 Mueller Blvd", state: "listed", list_price: 700_000)
    fake = FakeClient.new(grounded)
    use_client(fake) do
      # Non-pricing question -> routes to the orchestrator with the listing address.
      post agent_messages_path, params: { query: "tell me about the neighborhood", listing_id: listing.id }, as: :turbo_stream
    end
    assert_equal "500 Mueller Blvd", fake.last_args[:address]
  end

  class FakeValuation
    def initialize(result)
      @result = result
    end

    def valuation(**)
      @result
    end
  end

  def use_valuation(result)
    Agent::MessagesController.valuation_client_factory = -> { FakeValuation.new(result) }
    yield
  ensure
    Agent::MessagesController.valuation_client_factory = nil
  end

  def usable_valuation(estimate = 636_000)
    BrainValuationClient::Result.new(sufficient_data: true, estimate: estimate,
      low: estimate * 0.9, high: estimate * 1.1, facts: [], error: nil)
  end

  test "a pricing question on a listing answers with a real comparison, not a model dump" do
    listing = Property.create!(address: "1 Mueller", state: "listed", region: "Mueller", list_price: 525_000, photo_urls: ["x"])
    Comp.create!(region: "Mueller", address: "9 Comp", sale_price: 610_000, sale_date: Date.new(2026, 3, 1), source_name: "TCAD")

    # No brain client_factory set: the price-check path must NOT call orchestrate.
    use_valuation(usable_valuation(636_000)) do
      post agent_messages_path, params: { query: "Is this fairly priced compared to nearby sales?", listing_id: listing.id }, as: :turbo_stream
    end
    assert_response :success
    assert_match "This home is listed at", @response.body
    assert_match "$525,000", @response.body              # asking price
    assert_match "$636,000", @response.body              # Atlas estimate
    assert_match(/below/i, @response.body)               # asking below estimate
    assert_match "looks well-priced", @response.body     # plain verdict
    assert_match "How Atlas reached this", @response.body # detail demoted to reasoning
    assert_no_match(/contributes \$/, @response.body)     # not the raw attribution dump in the headline
  end

  test "a non-pricing question on a listing still uses the orchestrator" do
    listing = Property.create!(address: "1 Mueller", state: "listed", region: "Mueller", list_price: 525_000)
    use_client(FakeClient.new(grounded)) do
      post agent_messages_path, params: { query: "How many bedrooms does it have?", listing_id: listing.id }, as: :turbo_stream
    end
    assert_match "competitively priced", @response.body # the orchestrator's (fake) message
  end

  test "an escalated reply renders the broker handoff card" do
    handoff = BrainConversationClient::Result.new(
      outcome: "handoff", escalated: true, message: "Bringing in a broker.",
      handoff: BrainConversationClient::Handoff.new(trigger: "legal_complexity_upl", reason: "legal", hard: true),
      claims: [], steps: [], error: nil
    )
    use_client(FakeClient.new(handoff)) do
      post agent_messages_path, params: { query: "add a clause please" }, as: :turbo_stream
    end
    assert_match(/licensed broker/i, @response.body)
  end

  test "blank query is rejected" do
    post agent_messages_path, params: { query: "   " }, as: :turbo_stream
    assert_response :bad_request
  end

  test "a search request surfaces matching listings into the catalog (AE4), no brain call" do
    Property.create!(address: "10 Mueller Ct", state: "listed", region: "Mueller", list_price: 650_000, beds: 3, photo_urls: ["x"])
    Property.create!(address: "20 Tarry Ln", state: "listed", region: "Tarrytown", list_price: 1_500_000, beds: 4, photo_urls: ["x"])

    # No client_factory set: if the controller tried to reach the brain it would
    # use the real client; assert it did NOT by checking the search response.
    post agent_messages_path, params: { query: "show me 3-bed homes under $700k in Mueller" }, as: :turbo_stream
    assert_response :success
    assert_match "10 Mueller Ct", @response.body      # surfaced into the grid
    assert_no_match(/20 Tarry Ln/, @response.body)    # filtered out
    assert_match(/turbo-stream action=\"replace\" target=\"catalog\"/, @response.body)
  end

  test "a non-search question does not replace the catalog" do
    use_client(FakeClient.new(grounded)) do
      post agent_messages_path, params: { query: "is this a good deal?" }, as: :turbo_stream
    end
    assert_no_match(/target=\"catalog\"/, @response.body)
  end

  test "a degraded (brain-unavailable) result still renders a friendly message, not a 500" do
    degraded = BrainConversationClient::Result.new(
      outcome: "handoff", escalated: false, error: "agent_unavailable",
      message: "The assistant is taking a moment to respond.", claims: [], steps: []
    )
    use_client(FakeClient.new(degraded)) do
      post agent_messages_path, params: { query: "hello" }, as: :turbo_stream
    end
    assert_response :success
    assert_match(/taking a moment/i, @response.body)
  end
end
