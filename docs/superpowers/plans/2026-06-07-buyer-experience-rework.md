# Buyer Experience Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slim the buyer listing page to essentials, surface its analysis on demand through Ask Atlas suggested-prompt chips, and move buyer qualification out of two sidebar checkboxes into an optional buyer profile that drives intent triaging.

**Architecture:** Rails (`services/domain`). The listing page drops three always-on analysis cards; that data now flows through Atlas. The Ask Atlas sidebar gains chips that POST an explicit `insight` key, routed by `Agent::MessagesController` to deterministic, cited, DB-only answers — following the **existing handler-per-intent pattern** (`price_check_for`/`showing_for` + dedicated turbo-stream views), **not** a new `ListingInsights` service (the spec's sketch; the established controller pattern is DRYer and consistent). Buyer qualification becomes three nullable columns on `Visitor`, edited at `/buyer/profile`, read by `IntentTriage` via a thin adapter.

**Tech Stack:** Rails 8.1, Hotwire/Turbo + Stimulus, Minitest, SQLite (test). rbenv Ruby 3.3.11.

**Invariants (must hold):** zero RentCast/Anthropic on the request path (all insights read DB/cache) · photo **red-flags never shown to buyers** (feature findings only) · neutral-signals-only triage (profile collects only financing/timeline/budget, already on the allow-list).

**Spec:** `docs/superpowers/specs/2026-06-07-buyer-experience-rework-design.md`

**Shell setup (run once per session before any `bin/rails`):**
```bash
cd "/Users/rikki/Desktop/AI Real Estate Agent/.claude/worktrees/brain-pillars/services/domain"
eval "$(rbenv init - zsh)"   # Ruby 3.3.11; tests use SQLite, no Postgres needed
```
Full Rails suite: `bin/rails test`. Single test: `bin/rails test test/<path> -n <name>`.

---

## File Structure

- `db/migrate/20260607000002_add_buyer_profile_to_visitors.rb` — **create**: profile columns.
- `db/schema.rb` — **modify**: add columns to `visitors`, bump version to `2026_06_07_000002`.
- `app/models/visitor.rb` — **modify**: `buyer_signals` adapter + `record_buyer_profile`.
- `config/routes.rb` — **modify**: `resource :profile` under `buyer`.
- `app/controllers/buyer/profiles_controller.rb` — **create**: `edit`/`update`.
- `app/views/buyer/profiles/edit.html.erb` — **create**: profile form.
- `app/controllers/agent/messages_controller.rb` — **modify**: insight routing; remove checkbox triage.
- `app/views/agent/messages/neighborhood.turbo_stream.erb` + `_neighborhood.html.erb` — **create**.
- `app/views/agent/messages/photos.turbo_stream.erb` + `_photos.html.erb` — **create**.
- `app/views/shared/_agent_sidebar.html.erb` — **modify**: chips + hidden `insight`, remove checkboxes.
- `app/javascript/controllers/agent_sidebar_controller.js` — **modify**: `askPreset`, clear `insight` on submit-end.
- `app/controllers/buyer/listings_controller.rb` — **modify**: `show` drops `@comps`/`@reconciliation`/`@photo_analysis`.
- `app/views/buyer/listings/show.html.erb` — **modify**: remove three analysis cards.
- Tests under `test/models`, `test/controllers`, `test/integration`.
- Docs: `services/domain/README.md`, root `README.md`, spec status line.

---

## Task 1: Buyer-profile columns on Visitor + triage adapter

**Files:**
- Create: `db/migrate/20260607000002_add_buyer_profile_to_visitors.rb`
- Modify: `db/schema.rb:223-232` (visitors table) and `db/schema.rb:13` (version)
- Modify: `app/models/visitor.rb`
- Test: `test/models/visitor_test.rb`

- [ ] **Step 1: Write the failing test**

Add to `test/models/visitor_test.rb` (create the file if absent, with `require "test_helper"` and `class VisitorTest < ActiveSupport::TestCase`):

```ruby
test "record_buyer_profile: pre-approved AND <=30 days is high-intent and routes a handoff" do
  v = Visitor.create!(name: "Bea", email: "bea@example.com")
  assert_difference -> { Lead.count }, 1 do
    triage = v.record_buyer_profile(pre_approved: "yes", move_timeline_days: 30, budget_cents: 60_000_000)
    assert triage.high_intent?
  end
  assert v.reload.high_intent?
  assert v.handed_off?
end

test "record_buyer_profile: pre-approved but no near-term move is NOT high-intent" do
  v = Visitor.create!(name: "Lou", email: "lou@example.com")
  assert_no_difference -> { Lead.count } do
    triage = v.record_buyer_profile(pre_approved: "yes", move_timeline_days: 90, budget_cents: nil)
    refute triage.high_intent?
  end
  refute v.reload.high_intent?
end

test "buyer_signals maps profile columns to the neutral signal keys" do
  v = Visitor.new(pre_approved: "yes", move_timeline_days: 30, budget_cents: 50_000_000)
  assert_equal({ "preapproval" => "true", "move_timeline_days" => "30", "budget" => "50000000" }, v.buyer_signals)
  assert_equal({}, Visitor.new(pre_approved: "no").buyer_signals)
end
```

- [ ] **Step 2: Run it and watch it fail**

Run: `bin/rails test test/models/visitor_test.rb -n "/record_buyer_profile|buyer_signals/"`
Expected: FAIL — `unknown attribute 'pre_approved'` / `NoMethodError: record_buyer_profile`.

- [ ] **Step 3: Write the migration**

`db/migrate/20260607000002_add_buyer_profile_to_visitors.rb`:

```ruby
class AddBuyerProfileToVisitors < ActiveRecord::Migration[8.1]
  def change
    add_column :visitors, :pre_approved, :string          # "yes" / "no" / "unsure" / nil
    add_column :visitors, :move_timeline_days, :integer    # 7 / 30 / 90 / nil
    add_column :visitors, :budget_cents, :integer          # optional
  end
end
```

- [ ] **Step 4: Mirror into `db/schema.rb`** (local Postgres is not running; schema is hand-edited as in prior pillars)

Bump line 13 version to `2026_06_07_000002`, and inside `create_table "visitors"` add (keep columns alphabetthat-ish, matching existing style):

```ruby
    t.integer "budget_cents"
    t.integer "move_timeline_days"
    t.string "pre_approved"
```

- [ ] **Step 5: Implement the model methods**

In `app/models/visitor.rb`, add after `high_intent?`:

```ruby
  # Build the neutral buyer signal hash IntentTriage reads, from the profile
  # columns. Only allow-listed keys; empty values are dropped so they don't count.
  def buyer_signals
    {
      "preapproval"        => (pre_approved.to_s == "yes" ? "true" : ""),
      "move_timeline_days" => move_timeline_days&.to_s.to_s,
      "budget"             => budget_cents&.to_s.to_s
    }.reject { |_, v| v.to_s.strip.empty? }
  end

  # Persist the buyer profile and re-triage. Like record_engagement, the FIRST
  # time the visitor becomes high-intent we route one broker handoff.
  def record_buyer_profile(pre_approved:, move_timeline_days:, budget_cents:)
    assign_attributes(pre_approved: pre_approved.presence,
                      move_timeline_days: move_timeline_days,
                      budget_cents: budget_cents)
    triage = IntentTriage.call(signals: buyer_signals, side: "buyer")
    self.intent = triage.intent
    route_to_broker(triage, "buyer") if triage.high_intent? && !handed_off?
    save!
    triage
  end
```

- [ ] **Step 6: Run the tests — green**

Run: `bin/rails test test/models/visitor_test.rb -n "/record_buyer_profile|buyer_signals/"`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add db/migrate/20260607000002_add_buyer_profile_to_visitors.rb db/schema.rb app/models/visitor.rb test/models/visitor_test.rb
git commit -m "feat: buyer profile columns + triage adapter on Visitor"
```

---

## Task 2: Buyer profile page (/buyer/profile)

**Files:**
- Modify: `config/routes.rb:34-39`
- Create: `app/controllers/buyer/profiles_controller.rb`
- Create: `app/views/buyer/profiles/edit.html.erb`
- Test: `test/controllers/buyer/profiles_controller_test.rb`

- [ ] **Step 1: Write the failing controller test**

`test/controllers/buyer/profiles_controller_test.rb`:

```ruby
require "test_helper"

class Buyer::ProfilesControllerTest < ActionDispatch::IntegrationTest
  def sign_in(v) = post(session_path, params: { name: v.name, email: v.email })

  test "edit requires a signed-in visitor" do
    get edit_buyer_profile_path
    assert_redirected_to new_session_path
  end

  test "update persists the profile and re-triages to high-intent" do
    v = Visitor.create!(name: "Bea", email: "bea@example.com")
    sign_in v
    assert_difference -> { Lead.count }, 1 do
      patch buyer_profile_path, params: { pre_approved: "yes", move_timeline_days: "30", budget: "600000" }
    end
    v.reload
    assert_equal "yes", v.pre_approved
    assert_equal 30, v.move_timeline_days
    assert_equal 60_000_000, v.budget_cents
    assert v.high_intent?
    assert_redirected_to edit_buyer_profile_path
  end

  test "update with just-browsing leaves low-intent and no handoff" do
    v = Visitor.create!(name: "Lou", email: "lou@example.com")
    sign_in v
    assert_no_difference -> { Lead.count } do
      patch buyer_profile_path, params: { pre_approved: "no", move_timeline_days: "", budget: "" }
    end
    refute v.reload.high_intent?
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/controllers/buyer/profiles_controller_test.rb`
Expected: FAIL — no route `edit_buyer_profile_path`.

- [ ] **Step 3: Add the route**

In `config/routes.rb`, inside `namespace :buyer do` (after the `resources :listings ... end` block, before the closing `end`):

```ruby
    resource :profile, only: %i[edit update] # buyer qualification (R5)
```

- [ ] **Step 4: Implement the controller**

`app/controllers/buyer/profiles_controller.rb`:

```ruby
module Buyer
  # The buyer's qualification profile (financing / timeline / budget). Replaces
  # the per-message checkboxes: this is profile data, captured once and editable.
  # Saving re-runs IntentTriage and routes a high-intent lead to the broker (R5).
  class ProfilesController < ApplicationController
    layout "marketplace"
    before_action :require_visitor

    def edit
      @visitor = current_visitor
    end

    def update
      current_visitor.record_buyer_profile(
        pre_approved: params[:pre_approved],
        move_timeline_days: params[:move_timeline_days].presence&.to_i,
        budget_cents: dollars_to_cents(params[:budget])
      )
      redirect_to edit_buyer_profile_path, notice: "Profile saved — Atlas will tailor its help."
    end

    private

    def require_visitor
      redirect_to new_session_path unless signed_in?
    end

    def dollars_to_cents(raw)
      d = raw.to_s.gsub(/[^\d]/, "")
      d.empty? ? nil : d.to_i * 100
    end
  end
end
```

- [ ] **Step 5: Implement the view**

`app/views/buyer/profiles/edit.html.erb`:

```erb
<% content_for :title, "Your buyer profile — Atlas" %>
<div class="mk-card-section">
  <h1>Your buyer profile</h1>
  <p class="mk-muted">Tell Atlas where you are — it tailors help and brings in a licensed broker when you're ready. Optional, and only ever used to serve you better.</p>

  <%= form_with url: buyer_profile_path, method: :patch, class: "mk-auth-form" do %>
    <div class="mk-field">
      <label>Financing</label>
      <%= select_tag :pre_approved,
            options_for_select([["Yes — pre-approved", "yes"], ["Not yet", "no"], ["Not sure", "unsure"]], @visitor.pre_approved),
            include_blank: "Prefer not to say" %>
    </div>
    <div class="mk-field">
      <label>Move-in timeline</label>
      <%= select_tag :move_timeline_days,
            options_for_select([["As soon as possible", 7], ["Within 30 days", 30], ["1–3 months", 90]], @visitor.move_timeline_days),
            include_blank: "Just browsing" %>
    </div>
    <div class="mk-field">
      <label>Budget (optional)</label>
      <%= number_field_tag :budget, (@visitor.budget_cents ? @visitor.budget_cents / 100 : nil), min: 0, placeholder: "600000" %>
    </div>
    <%= submit_tag "Save profile", class: "mk-btn" %>
  <% end %>
</div>
```

- [ ] **Step 6: Run the tests — green**

Run: `bin/rails test test/controllers/buyer/profiles_controller_test.rb`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add config/routes.rb app/controllers/buyer/profiles_controller.rb app/views/buyer/profiles/edit.html.erb test/controllers/buyer/profiles_controller_test.rb
git commit -m "feat: buyer profile page drives intent triaging"
```

---

## Task 3: Remove the two sidebar checkboxes + the per-message triage path

**Files:**
- Modify: `app/views/shared/_agent_sidebar.html.erb:45-51`
- Modify: `app/controllers/agent/messages_controller.rb` (remove `triage_visitor` call + method)
- Test: `test/controllers/agent/messages_controller_test.rb`

- [ ] **Step 1: Write the failing test** (asserts the checkbox path is gone — posting `preapproval`/`move_soon` no longer creates a lead)

Add to `test/controllers/agent/messages_controller_test.rb` (create with `require "test_helper"` + `class Agent::MessagesControllerTest < ActionDispatch::IntegrationTest` if absent; stub the brain so free-text doesn't hit gRPC):

```ruby
def stub_brain!
  fake = Struct.new(:message).new("ok")
  Agent::MessagesController.client_factory = -> { Class.new { def orchestrate(**) = Struct.new(:message).new("ok") end.new } }
end
def unstub_brain! = Agent::MessagesController.client_factory = nil

test "posting legacy preapproval/move_soon no longer triages (no lead created)" do
  v = Visitor.create!(name: "Bea", email: "bea@example.com")
  post session_path, params: { name: v.name, email: v.email }
  stub_brain!
  assert_no_difference -> { Lead.count } do
    post agent_messages_path, params: { query: "hello there", preapproval: "1", move_soon: "1" }, as: :turbo_stream
  end
ensure
  unstub_brain!
end
```

- [ ] **Step 2: Run it — fail** (today the checkbox path creates a Lead)

Run: `bin/rails test test/controllers/agent/messages_controller_test.rb -n "/legacy preapproval/"`
Expected: FAIL — `Lead.count` changed by 1.

- [ ] **Step 3: Remove the checkboxes from the sidebar**

In `app/views/shared/_agent_sidebar.html.erb`, delete lines 45-51 (the `<%# Neutral buyer signals … %>` comment through the closing `<% end %>` of the `signed_in?` block).

- [ ] **Step 4: Remove the triage call + method from the controller**

In `app/controllers/agent/messages_controller.rb`: delete line 17 (`triage_visitor # …`) and delete the entire `triage_visitor` private method (lines 46-59 incl. its leading comment).

- [ ] **Step 5: Run the test — green**

Run: `bin/rails test test/controllers/agent/messages_controller_test.rb -n "/legacy preapproval/"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/views/shared/_agent_sidebar.html.erb app/controllers/agent/messages_controller.rb test/controllers/agent/messages_controller_test.rb
git commit -m "refactor: drop per-message intent checkboxes (profile drives triage)"
```

---

## Task 4: Insight routing in Agent::MessagesController

**Files:**
- Modify: `app/controllers/agent/messages_controller.rb`
- Test: `test/controllers/agent/messages_controller_test.rb`

- [ ] **Step 1: Write the failing tests** (chip keys route to deterministic answers; the brain is NOT called; photos answer excludes red-flags)

Add to `test/controllers/agent/messages_controller_test.rb`:

```ruby
def make_listing
  Property.create!(address: "9 Demo St, Austin TX 78704", state: "listed", region: "Zilker",
                   list_price: 625_000, sqft: 1850, beds: 3, baths: 2,
                   photo_urls: ["https://example.test/a.jpg"], source_name: "S", captured_at: Time.current)
end

# Brain factory that fails the test if the orchestrator is ever called for a chip.
def forbid_brain!
  Agent::MessagesController.client_factory = -> {
    Class.new { def orchestrate(**) ; raise "brain should not be called for an insight chip"; end }.new
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
  called = false
  Agent::MessagesController.client_factory = -> {
    Class.new { def orchestrate(**) ; Struct.new(:message).new("from brain") ; end }.new
  }
  post agent_messages_path, params: { query: "tell me about schools" }, as: :turbo_stream
  assert_response :success
  assert_match(/from brain/, @response.body)
ensure
  Agent::MessagesController.client_factory = nil
end
```

> Note: `PhotoAnalysis` JSON columns are `findings` (buyer-safe features, read via `feature_findings`) and `needs_review` (red-flags, read via `review_findings`). The factory above uses those exact column names.

- [ ] **Step 2: Run them — fail**

Run: `bin/rails test test/controllers/agent/messages_controller_test.rb -n "/chip|free text/"`
Expected: FAIL — `insight` not handled; neighborhood/photos views missing.

- [ ] **Step 3: Add insight routing to the controller**

In `app/controllers/agent/messages_controller.rb#create`, replace the intent dispatch block (the original `@intent = SearchIntent.detect(@query)` through the `else … end`) with:

```ruby
      if handle_insight
        # A suggested-prompt chip: deterministic, cited, DB-only (no brain call).
      elsif (@intent = SearchIntent.detect(@query))
        @listings = ListingSearch.new(**@intent.to_search_params).results
      elsif (@price_check = price_check_for(@listing, @query))
      elsif (@showing = showing_for(@listing, @query))
      else
        @result = brain_client.orchestrate(query: @query, address: @address, thread_id: agent_thread_id)
        @delivery = ChannelTransport.deliver(channel: @channel, to: current_visitor&.email || "buyer", body: @result.message)
      end
```

Add these private methods (near `showing_for`):

```ruby
    # A suggested-prompt chip carries an explicit `insight` key + a pinned
    # listing → a deterministic, cited answer from data we already hold. Returns
    # true when handled (sets the ivars its view reads), false to fall through.
    def handle_insight
      @insight_key = params[:insight].to_s
      return false unless @listing && %w[price neighborhood photos tour].include?(@insight_key)

      case @insight_key
      when "price"        then @price_check = price_check_for(@listing, @query, force: true)
      when "neighborhood" then @neighborhood = CrossSourceReconciliation.for(property: @listing)
      when "photos"       then @photo_insight = PhotoAnalysis.find_by("lower(address) = ?", @listing.address.downcase)
      when "tour"
        @showing_kind = "tour"
        @showing = ShowingScheduler.available_slots(property: @listing, now: Time.current, kind: "tour")
      end
      true
    end
```

Change `price_check_for` to accept `force:` (skip the keyword gate for a chip):

```ruby
    def price_check_for(listing, query, force: false)
      return nil unless listing && (force || PriceCheck.pricing_question?(query))

      @valuation = ValuationAssembly.new(address: listing.address, client: valuation_client).call
      comps = Comp.in_region(listing.region).recent_first.limit(3)
      result = PriceCheck.for(property: listing, valuation: @valuation, comps: comps)
      result.usable? ? result : nil
    end
```

Update `view_for` to honor the insight key first:

```ruby
    def view_for
      return "neighborhood" if @insight_key == "neighborhood"
      return "photos" if @insight_key == "photos"
      return "search" if @intent
      return "price_check" if @price_check
      return "showing" if @showing

      "create"
    end
```

- [ ] **Step 4: Run the tests** (they will still fail until Task 5 adds the views — that's expected; the `free text` case should already pass)

Run: `bin/rails test test/controllers/agent/messages_controller_test.rb -n "/free text/"`
Expected: PASS. (neighborhood/photos remain red pending Task 5.)

- [ ] **Step 5: Commit**

```bash
git add app/controllers/agent/messages_controller.rb test/controllers/agent/messages_controller_test.rb
git commit -m "feat: route Atlas insight chips to cited, DB-only answers"
```

---

## Task 5: Neighborhood + photos turbo-stream views

**Files:**
- Create: `app/views/agent/messages/neighborhood.turbo_stream.erb`
- Create: `app/views/agent/messages/_neighborhood.html.erb`
- Create: `app/views/agent/messages/photos.turbo_stream.erb`
- Create: `app/views/agent/messages/_photos.html.erb`
- Test: reuse the Task 4 chip tests.

- [ ] **Step 1: Confirm the tests are red for the right reason**

Run: `bin/rails test test/controllers/agent/messages_controller_test.rb -n "/chip/"`
Expected: FAIL — missing template `agent/messages/neighborhood` / `photos`.

- [ ] **Step 2: Create the neighborhood stream + partial** (mirrors `showing.turbo_stream.erb`)

`app/views/agent/messages/neighborhood.turbo_stream.erb`:

```erb
<%= turbo_stream.append "agent-messages" do %>
  <div class="agent-msg agent-msg--user">
    <div class="agent-bubble"><%= @query %></div>
    <% if @listing %><div class="agent-ctx">about <%= @listing.address %></div><% end %>
  </div>
<% end %>

<%= turbo_stream.append "agent-messages" do %>
  <%= render "agent/messages/neighborhood", rec: @neighborhood, listing: @listing %>
<% end %>
```

`app/views/agent/messages/_neighborhood.html.erb`:

```erb
<div class="agent-msg agent-msg--bot">
  <div class="agent-bubble">
    <% if rec&.market_ppsf %>
      <p>
        <% if rec.signal %>
          <strong><%= rec.signal == :hot ? "Seller's market" : (rec.signal == :cool ? "Room to negotiate" : "Balanced market") %>.</strong>
        <% end %>
        <%= rec.signal_reason %>
      </p>
      <ul class="agent-facts">
        <li>Market <strong>$<%= rec.market_ppsf %></strong>/sqft<% if rec.subject_ppsf %> · this home <strong>$<%= rec.subject_ppsf %></strong>/sqft<% end %></li>
        <% if rec.market_median %><li>ZIP median <strong><%= number_to_currency(rec.market_median, precision: 0) %></strong></li><% end %>
      </ul>
      <% market_src = rec.sources.find { |s| s.source_id.to_s.start_with?("market:") } %>
      <% if market_src %><div class="agent-ctx">Source: <%= market_src.source_id %><% if market_src.as_of.present? %> · as of <%= market_src.as_of.to_date.strftime("%b %-d, %Y") rescue market_src.as_of %><% end %>.</div><% end %>
    <% else %>
      I don't have neighborhood market data for this home yet.
    <% end %>
  </div>
</div>
```

- [ ] **Step 3: Create the photos stream + partial** (feature findings only — never `review_findings`)

`app/views/agent/messages/photos.turbo_stream.erb`:

```erb
<%= turbo_stream.append "agent-messages" do %>
  <div class="agent-msg agent-msg--user">
    <div class="agent-bubble"><%= @query %></div>
    <% if @listing %><div class="agent-ctx">about <%= @listing.address %></div><% end %>
  </div>
<% end %>

<%= turbo_stream.append "agent-messages" do %>
  <%= render "agent/messages/photos", pa: @photo_insight %>
<% end %>
```

`app/views/agent/messages/_photos.html.erb`:

```erb
<div class="agent-msg agent-msg--bot">
  <div class="agent-bubble">
    <% if pa&.feature_findings&.any? %>
      <p>Here's what the listing photos show:</p>
      <ul class="agent-facts">
        <% pa.feature_findings.each do |f| %>
          <li><%= f["label"].to_s.tr("_", " ").capitalize %> — <%= (f["confidence"].to_f * 100).round %>% confident</li>
        <% end %>
      </ul>
      <% if pa.condition.present? %>
        <p>Photo-derived condition: <strong><%= (pa.condition.to_f * 100).round %>/100</strong> — this feeds my valuation.</p>
      <% end %>
      <div class="agent-ctx">Source: <%= pa.from_claude? ? "Claude vision analysis" : "sample analysis (demo)" %>. Any visible defects are routed to a licensed broker, never asserted here.</div>
    <% else %>
      I don't have a photo read for this home yet.
    <% end %>
  </div>
</div>
```

- [ ] **Step 4: Run the chip tests — green**

Run: `bin/rails test test/controllers/agent/messages_controller_test.rb -n "/chip/"`
Expected: PASS — neighborhood shows `/sqft`; photos shows "updated kitchen" and **not** "foundation".

- [ ] **Step 5: Commit**

```bash
git add app/views/agent/messages/neighborhood.turbo_stream.erb app/views/agent/messages/_neighborhood.html.erb app/views/agent/messages/photos.turbo_stream.erb app/views/agent/messages/_photos.html.erb
git commit -m "feat: neighborhood + photos Atlas answer views (red-flags excluded)"
```

---

## Task 6: Suggested-prompt chips in the sidebar

**Files:**
- Modify: `app/views/shared/_agent_sidebar.html.erb`
- Modify: `app/javascript/controllers/agent_sidebar_controller.js`
- Test: `test/integration/agent_chips_test.rb`

- [ ] **Step 1: Write the failing integration test** (chips render on a listing page)

`test/integration/agent_chips_test.rb`:

```ruby
require "test_helper"

class AgentChipsTest < ActionDispatch::IntegrationTest
  test "the listing page renders Atlas suggested-prompt chips" do
    l = Property.create!(address: "9 Demo St, Austin TX 78704", state: "listed", region: "Zilker",
                         list_price: 625_000, sqft: 1850, beds: 3, baths: 2,
                         photo_urls: ["https://example.test/a.jpg"], source_name: "S", captured_at: Time.current)
    get buyer_listing_path(l)
    assert_response :success
    assert_select "[data-insight='neighborhood']"
    assert_select "[data-insight='photos']"
    assert_select "[data-insight='price']"
    assert_select "[data-insight='tour']"
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/integration/agent_chips_test.rb`
Expected: FAIL — no `[data-insight]` elements.

- [ ] **Step 3: Add the hidden insight field + chips to the sidebar**

In `app/views/shared/_agent_sidebar.html.erb`, after the two existing `hidden_field_tag` lines (address, listing_id) add:

```erb
    <%= hidden_field_tag :insight, "", data: { agent_sidebar_target: "insight" } %>
```

And immediately above the `<div class="agent-input-row">` add the chips row:

```erb
    <%# Suggested prompts — deterministic, cited answers about the pinned home. %>
    <div class="agent-chips">
      <% [["Is this fairly priced?", "price"], ["How's this neighborhood?", "neighborhood"],
          ["What do the photos show?", "photos"], ["Can I tour this week?", "tour"]].each do |label, key| %>
        <button type="button" class="mk-btn mk-btn--ghost agent-chip"
                data-insight="<%= key %>" data-preset="<%= label %>"
                data-action="agent-sidebar#askPreset"><%= label %></button>
      <% end %>
    </div>
```

- [ ] **Step 4: Wire the Stimulus controller**

In `app/javascript/controllers/agent_sidebar_controller.js`, add `"insight"` to `static targets`:

```js
  static targets = ["messages", "input", "thinking", "address", "listingId", "form", "mic", "channel", "insight"]
```

Add an `askPreset` method (after `enter`):

```js
  // A suggested-prompt chip: fill the box with the preset, tag the turn with its
  // insight key, and submit. The key routes to a deterministic, cited answer.
  askPreset(event) {
    const el = event.currentTarget
    this.inputTarget.value = el.dataset.preset || ""
    if (this.hasInsightTarget) this.insightTarget.value = el.dataset.insight || ""
    this.formTarget.requestSubmit()
  }
```

In `end()`, clear the insight key after each submit so a later free-text turn isn't mis-tagged. Change `end()` to:

```js
  end() {
    if (this.hasThinkingTarget) this.thinkingTarget.hidden = true
    this.inputTarget.value = ""
    if (this.hasInsightTarget) this.insightTarget.value = ""
    this.scrollToBottom()
  }
```

- [ ] **Step 5: Run the test — green**

Run: `bin/rails test test/integration/agent_chips_test.rb`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/views/shared/_agent_sidebar.html.erb app/javascript/controllers/agent_sidebar_controller.js test/integration/agent_chips_test.rb
git commit -m "feat: Atlas suggested-prompt chips"
```

---

## Task 7: Slim the listing page

**Files:**
- Modify: `app/controllers/buyer/listings_controller.rb:17-27`
- Modify: `app/views/buyer/listings/show.html.erb`
- Test: `test/integration/listing_page_slim_test.rb`

- [ ] **Step 1: Write the failing test** (the three analysis cards are gone; the schedule widget stays)

`test/integration/listing_page_slim_test.rb`:

```ruby
require "test_helper"

class ListingPageSlimTest < ActionDispatch::IntegrationTest
  setup do
    @l = Property.create!(address: "9 Demo St, Austin TX 78704", state: "listed", region: "Zilker",
                          list_price: 625_000, sqft: 1850, beds: 3, baths: 2,
                          photo_urls: ["https://example.test/a.jpg"], source_name: "S", captured_at: Time.current)
    MarketSnapshot.create!(zip: "78704", area: "Zilker", median_price: 700_000, avg_price_per_sqft: 380, avg_days_on_market: 18, as_of: Time.current)
    PhotoAnalysis.create!(address: @l.address, property: @l, analyzed_at: Time.current, condition: 0.7, provenance: "sample",
                          findings: [{ "kind" => "feature", "label" => "updated_kitchen", "confidence" => 0.9, "evidence_photo_id" => "a" }])
  end

  test "analysis cards are removed; schedule + offer stay" do
    get buyer_listing_path(@l)
    assert_response :success
    assert_select "#neighborhood-pulse", false
    assert_select "#photo-analysis", false
    assert_select "h2", text: "Recent nearby sales", count: 0
    assert_select "#schedule-showing"                      # interactive widget stays
    assert_select "a", text: "Make an offer →"
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/integration/listing_page_slim_test.rb`
Expected: FAIL — the three cards still render.

- [ ] **Step 3: Trim the controller**

In `app/controllers/buyer/listings_controller.rb#show`, keep `@listing` and `@showings`; delete the `@comps`, `@reconciliation`, and `@photo_analysis` lines. Result:

```ruby
    def show
      @listing = Property.browsable.find(params[:id])
      # Real, collision-aware showing slots for the request form (R6).
      @showings = ShowingScheduler.available_slots(property: @listing, now: Time.current)
      # Listing analysis (neighborhood / photos / price) is now answered on demand
      # through Ask Atlas, not stacked on the page.
    end
```

- [ ] **Step 4: Trim the view**

In `app/views/buyer/listings/show.html.erb`, delete three blocks:
- the Neighborhood pulse block (`<% if @reconciliation&.market_ppsf %> … <% end %>`, lines 53-73),
- the photo-analysis block (`<% if @photo_analysis&.feature_findings&.any? %> … <% end %>`, lines 75-91),
- the Recent nearby sales block (`<% if @comps.any? %> … <% end %>`, lines 98-109).

Keep: gallery, head, facts, Make-an-offer, `#schedule-showing`, About, footer.

- [ ] **Step 5: Run the test — green**

Run: `bin/rails test test/integration/listing_page_slim_test.rb`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/controllers/buyer/listings_controller.rb app/views/buyer/listings/show.html.erb test/integration/listing_page_slim_test.rb
git commit -m "feat: slim listing page — analysis moves into Ask Atlas"
```

---

## Task 8: Docs + full suite + final commit

**Files:**
- Modify: `services/domain/README.md`
- Modify: root `README.md` (capability/UX note + test counts)
- Modify: `docs/superpowers/specs/2026-06-07-buyer-experience-rework-design.md` (status → Implemented)

- [ ] **Step 1: Update `services/domain/README.md`** — add a short subsection under the agent/marketplace docs:

```markdown
## Ask Atlas suggested prompts (buyer page)

The listing page stays lean (photos, price, facts, offer, schedule). Listing
analysis is answered on demand by **Ask Atlas** via suggested-prompt chips —
"Is this fairly priced?" (PriceCheck + cross-source), "How's this neighborhood?"
(CrossSourceReconciliation), "What do the photos show?" (PhotoAnalysis **feature
findings only** — red-flags stay broker-only), "Can I tour this week?"
(ShowingScheduler). Each chip POSTs an explicit `insight` key; all answers are
DB/cache-read (zero external calls). Buyer qualification lives on the **buyer
profile** (`/buyer/profile`: pre-approval / move-in timeline / budget), which
drives `IntentTriage` (R5); the old per-message checkboxes are gone.
```

- [ ] **Step 2: Update root `README.md`** — adjust the buyer-UX description and the Rails test count to the new total (run `bin/rails test` first to get it).

- [ ] **Step 3: Flip the spec status line** to `Status: Implemented` in the design doc header.

- [ ] **Step 4: Run the FULL Rails suite — all green**

Run: `bin/rails test`
Expected: PASS — prior 283 + the new cases, 0 failures / 0 errors. (Brain suite is untouched.)

- [ ] **Step 5: Final commit**

```bash
git add services/domain/README.md README.md docs/superpowers/specs/2026-06-07-buyer-experience-rework-design.md
git commit -m "docs: buyer experience rework — chips, profile, slim listing page"
```

---

## Self-Review

**Spec coverage:**
- Slim page (spec A) → Task 7. ✓
- Atlas chips + cited answers reusing existing services (spec B) → Tasks 4, 5, 6. ✓ (Architecture deviation from the spec's `ListingInsights` service documented in the header — controller-handler pattern instead.)
- Buyer profile replaces checkboxes; IntentTriage rewired (spec C) → Tasks 1, 2, 3. ✓
- Invariants: zero external calls (all handlers DB/cache) ✓; red-flags broker-only (Task 5 `_photos` uses `feature_findings`, test asserts exclusion) ✓; neutral-signals-only (profile fields are on the allow-list) ✓.
- Testing section → every task is TDD with a named test + expected fail/pass. ✓

**Placeholder scan:** none — every code/step is concrete.

**Type/name consistency:** `record_buyer_profile`, `buyer_signals`, `@insight_key`, `@neighborhood`, `@photo_insight`, `handle_insight`, `price_check_for(..., force:)`, `view_for` keys, `data-insight`/`askPreset`/`insight` target — all consistent across tasks. Migration version `2026_06_07_000002` matches the schema bump. Chip keys (`price`/`neighborhood`/`photos`/`tour`) match `handle_insight`'s allow-list and `view_for`.

**Implementer note:** `PhotoAnalysis` writers are `findings` + `needs_review`; readers are `feature_findings` + `review_findings` (`app/models/photo_analysis.rb`). The plan's factories use the writer column names.
