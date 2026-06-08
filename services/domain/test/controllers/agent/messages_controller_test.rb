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

  test "the price-check reasoning shows each feature's signed dollar effect, not bare labels" do
    listing = Property.create!(address: "1 Mueller", state: "listed", region: "Mueller", list_price: 525_000, photo_urls: ["x"])
    facts = [
      BrainValuationClient::Fact.new(kind: "feature:sqft", description: "Living area (sqft)", contribution: -121_208.0, source_id: "s1"),
      BrainValuationClient::Fact.new(kind: "feature:baths", description: "Bathroom count", contribution: 14_256.0, source_id: "s2"),
    ]
    valuation = BrainValuationClient::Result.new(sufficient_data: true, estimate: 636_000,
      low: 600_000, high: 680_000, facts: facts, error: nil)

    use_valuation(valuation) do
      post agent_messages_path, params: { query: "Is this fairly priced?", listing_id: listing.id }, as: :turbo_stream
    end
    assert_response :success
    assert_match "What drives this estimate", @response.body
    # The actual dollar effect is shown (sorted biggest-first), with direction —
    # not a vague bare feature name.
    assert_match "Living area (sqft)", @response.body
    assert_match(/−\s*\$121,208/, @response.body)  # sqft pulls the estimate DOWN
    assert_match(/\+\s*\$14,256/, @response.body)   # baths push it UP
    assert_no_match(/uncalibrated/, @response.body) # the trust-eroding caveat is gone
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

  test "a non-chat channel tags the message bubble and shows simulated delivery (SMS/Email seam)" do
    use_client(FakeClient.new(grounded)) do
      post agent_messages_path, params: { query: "hi", channel: "sms" }, as: :turbo_stream
    end
    assert_match(/agent-channel/, @response.body)
    assert_match(/sms/, @response.body)
    assert_match(/delivered via sms/i, @response.body)
    assert_match(/simulated/i, @response.body) # honest: no live carrier
  end

  test "a chat reply has no out-of-band delivery note" do
    use_client(FakeClient.new(grounded)) do
      post agent_messages_path, params: { query: "hi", channel: "chat" }, as: :turbo_stream
    end
    assert_no_match(/delivered via/i, @response.body)
  end

  test "legacy preapproval/move_soon params no longer triage (qualification moved to the profile)" do
    post session_path, params: { name: "Bea Buyer", email: "bea@example.com" } # sign in
    use_client(FakeClient.new(grounded)) do
      assert_no_difference "Lead.count" do
        post agent_messages_path,
             params: { query: "I'm ready", preapproval: "1", move_soon: "1" }, as: :turbo_stream
      end
    end
    refute Visitor.find_by(email: "bea@example.com").high_intent?
  end

  test "agent sidebar price check is grounded in real comps + freshness" do
    listing = Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                               list_price: 500_000, sqft: 2000, beds: 4, baths: 2.5, year_built: 1998,
                               photo_urls: ["x"], source_name: "RentCast (live listing data)",
                               captured_at: Time.current)
    Property.create!(address: "2 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 520_000, sqft: 2050, beds: 4, baths: 2,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)
    MarketSnapshot.create!(zip: "78704", area: "Austin 78704", median_price: 600_000,
                           new_listings: 3, avg_days_on_market: 21, as_of: Date.new(2026, 6, 5))

    # Inject a client that returns a comp:active_listing fact so the view renders the citation.
    comp_result = BrainValuationClient::Result.new(
      sufficient_data: true, estimate: 490_000, low: 450_000, high: 530_000,
      facts: [BrainValuationClient::Fact.new(
        source_id: "comp:2", kind: "comp:active_listing",
        description: "Active listing 2 Oak St: $520,000 ($253/sqft, 0.0 mi, listed 0d ago)",
        contribution: 0.0
      )],
      as_of: nil, recent_activity: nil, error: nil
    )

    use_valuation(comp_result) do
      post agent_messages_path,
           params: { query: "Is this fairly priced?", listing_id: listing.id },
           as: :turbo_stream
    end

    assert_response :success
    assert_match(/Active listing/i, @response.body)  # comp citation surfaced
  end

  test "a price check reconciles asking against tax assessment + ZIP market (R1 cross-source)" do
    listing = Property.create!(address: "1 Oak St, Austin, TX 78704", state: "listed", region: "Zilker",
                               list_price: 600_000, sqft: 2000, beds: 4, baths: 2.5, year_built: 1998,
                               photo_urls: ["x"], source_name: "RentCast (live listing data)", captured_at: Time.current)
    PropertyRecordCache.create!(address: "1 Oak St, Austin, TX 78704", region: "Zilker", sqft: 2000,
                                tax_assessed_value: 500_000, captured_at: Time.current)
    MarketSnapshot.create!(zip: "78704", area: "Zilker", median_price: 580_000, avg_price_per_sqft: 270,
                           avg_days_on_market: 18, new_listings: 4, as_of: Date.new(2026, 6, 5), source: "Curated Austin sample")

    use_valuation(usable_valuation(620_000)) do
      post agent_messages_path, params: { query: "Is this fairly priced?", listing_id: listing.id }, as: :turbo_stream
    end

    assert_response :success
    assert_match "Cross-source check", @response.body
    assert_match "County tax assessment", @response.body  # captured-but-unused source now surfaced
    assert_match "tax:tcad", @response.body                # cited
    assert_match(/county tax assessment/i, @response.body) # asking-vs-tax delta line
    assert_match(/\$300\/sqft/, @response.body)            # subject $/sqft vs market
    assert_match(/Priced above the neighborhood/, @response.body) # hot signal reason (300 vs 270)
  end

  test "a scheduling request on a listing surfaces real available slots, no brain call" do
    listing = Property.create!(address: "7 Tour St", state: "listed", region: "Austin 78704",
                               list_price: 500_000, sqft: 2000, beds: 3, baths: 2)
    # No client_factory set: a brain round-trip would use the real client. The
    # scheduling path answers Rails-side instead.
    post agent_messages_path, params: { query: "Can I tour this house Friday?", listing_id: listing.id }, as: :turbo_stream

    assert_response :success
    assert_match(/open tour times/i, @response.body)
    # bookable slot buttons post to the buyer showings endpoint
    assert_match(%r{/buyer/listings/#{listing.id}/showings}, @response.body)
  end

  test "a scheduling request without a pinned listing falls through to the orchestrator" do
    use_client(FakeClient.new(grounded)) do
      post agent_messages_path, params: { query: "I'd like to schedule a showing" }, as: :turbo_stream
    end
    assert_match "competitively priced", @response.body # the orchestrator's (fake) message
  end

  test "a blacked-out listing shows an honest no-slots reason in the sidebar" do
    listing = Property.create!(address: "8 Sold St", state: "under_offer", region: "Austin 78704",
                               list_price: 500_000, sqft: 2000, beds: 3, baths: 2)
    post agent_messages_path, params: { query: "can I tour it?", listing_id: listing.id }, as: :turbo_stream

    assert_response :success
    assert_match(/can't offer tour times/i, @response.body)
    assert_match(/under_offer/, @response.body)
  end

  # --- suggested-prompt chips: deterministic, cited, DB-only (no brain call) ---

  def make_listing
    Property.create!(address: "9 Demo St, Austin TX 78704", state: "listed", region: "Zilker",
                     list_price: 625_000, sqft: 1850, beds: 3, baths: 2,
                     photo_urls: ["https://example.test/a.jpg"], source_name: "S", captured_at: Time.current)
  end

  # A brain factory that fails the test if the orchestrator is ever called.
  def forbid_brain!
    Agent::MessagesController.client_factory = lambda {
      Class.new { def orchestrate(**) = raise("brain should not be called for an insight chip") }.new
    }
  end

  test "neighborhood chip answers from cross-source data without calling the brain" do
    forbid_brain!
    l = make_listing
    MarketSnapshot.create!(zip: "78704", area: "Zilker", median_price: 700_000, avg_price_per_sqft: 380, avg_days_on_market: 18, as_of: Time.current)
    post agent_messages_path, params: { query: "How's this neighborhood?", insight: "neighborhood", listing_id: l.id }, as: :turbo_stream
    assert_response :success
    assert_match(/sqft/, @response.body)
  ensure
    Agent::MessagesController.client_factory = nil
  end

  test "photos chip shows feature findings only, never red-flags" do
    forbid_brain!
    l = make_listing
    PhotoAnalysis.create!(address: l.address, property: l, analyzed_at: Time.current, condition: 0.7,
                          provenance: "sample",
                          findings: [{ "kind" => "feature", "label" => "updated_kitchen", "confidence" => 0.9, "evidence_photo_id" => "a" }],
                          needs_review: [{ "kind" => "red_flag", "label" => "foundation_crack", "confidence" => 0.8, "evidence_photo_id" => "a" }])
    post agent_messages_path, params: { query: "What do the photos show?", insight: "photos", listing_id: l.id }, as: :turbo_stream
    assert_response :success
    assert_match(/updated kitchen/i, @response.body)
    refute_match(/foundation/i, @response.body) # red-flag never reaches the buyer
  ensure
    Agent::MessagesController.client_factory = nil
  end

  test "free text without an insight key still reaches the brain" do
    use_client(FakeClient.new(grounded)) do
      post agent_messages_path, params: { query: "tell me about schools" }, as: :turbo_stream
    end
    assert_response :success
    assert_match(/competitively priced/, @response.body) # the orchestrator's (fake) message
  end
end
