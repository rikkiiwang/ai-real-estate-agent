# Omnichannel (R4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent one persisted cross-channel conversation thread (Voice/SMS/Email/Chat) so it keeps context when a lead switches channels, with real Twilio/SendGrid adapters + inbound webhooks behind the ENV gate, a broker cross-channel transcript, and the voice service wired into the same thread.

**Architecture:** A Rails `Conversation` (keyed by contact) + `Message` is the durable thread; the brain's `thread_id` points at it (no proto change — LangGraph already keys memory by thread_id). The sidebar, inbound webhooks, and the voice service all append through the same path. Real providers fire only when configured; otherwise the `Simulated` transport keeps the demo external-call-free.

**Tech Stack:** Rails 8.1 (Hotwire), Go (voice), Minitest, SQLite (Rails test). rbenv Ruby 3.3.11.

**Invariants:** zero external calls in the demo (simulated transport) · AI disclosure recorded per message · neutral-signals triage unchanged · no proto change.

**Spec:** `docs/superpowers/specs/2026-06-08-omnichannel-design.md`

**Shell setup (Rails):**
```bash
cd "/Users/rikki/Desktop/AI Real Estate Agent/.claude/worktrees/brain-pillars/services/domain"
eval "$(rbenv init - zsh)"
```
Rails suite: `bin/rails test`. Go: `cd <repo root> && go test ./services/voice/...`. Work from the worktree paths shown above.

---

## File Structure

- `db/migrate/20260608000003_create_conversations_and_messages.rb` + `db/schema.rb` — the thread tables.
- `app/models/conversation.rb`, `app/models/message.rb` — **create**.
- `app/models/visitor.rb` — **modify**: `#conversation`.
- `app/services/agent_reply_summary.rb` — **create**: answer → thread line.
- `app/controllers/agent/messages_controller.rb` — **modify**: persist turns + thread_id.
- `app/views/shared/_agent_sidebar.html.erb` — **modify**: render history.
- `app/services/channel_transport.rb` — **modify**: real Twilio/SendGrid + http helpers.
- `app/services/inbound_turn.rb` — **create**: append → orchestrate → append.
- `app/controllers/inbound/base_controller.rb`, `sms_controller.rb`, `email_controller.rb`, `voice_controller.rb` — **create**.
- `config/routes.rb` — **modify**: `namespace :inbound`.
- `app/models/visitor.rb` — **modify**: `route_to_broker` populates transcript.
- `services/voice/relay.go` + `services/voice/main.go` — **create/modify**: call Rails.
- Tests under `test/...` and `services/voice/*_test.go`.
- Docs: `services/domain/README.md`, root `README.md`, `deploy/fly/DEPLOY.md`, spec status.

---

## Task 1: Conversation + Message models

**Files:**
- Create: `db/migrate/20260608000003_create_conversations_and_messages.rb`
- Modify: `db/schema.rb`
- Create: `app/models/conversation.rb`, `app/models/message.rb`
- Test: `test/models/conversation_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/models/conversation_test.rb`:

```ruby
require "test_helper"

class ConversationTest < ActiveSupport::TestCase
  test "find-or-create by normalized contact (email lowercased, phone digits)" do
    a = Conversation.for(contact: "Jordan@Example.com", name: "Jordan")
    b = Conversation.for(contact: "jordan@example.com")
    assert_equal a.id, b.id
    p1 = Conversation.for(contact: "+1 (512) 555-0100")
    p2 = Conversation.for(contact: "+15125550100")
    assert_equal p1.id, p2.id
  end

  test "append records a channel-tagged message and updates last_channel" do
    c = Conversation.for(contact: "j@x.com")
    c.append(channel: "chat", role: "user", body: "hi")
    c.append(channel: "sms", role: "agent", body: "hello", ai_disclosed: false)
    assert_equal %w[chat sms], c.messages.map(&:channel)
    assert_equal "sms", c.reload.last_channel
  end

  test "thread_id and transcript" do
    c = Conversation.for(contact: "j@x.com")
    c.append(channel: "chat", role: "user", body: "what's it worth?")
    c.append(channel: "voice", role: "agent", body: "About $610k.")
    assert_equal "conv-#{c.id}", c.thread_id
    assert_equal "[chat] user: what's it worth?\n[voice] agent: About $610k.", c.transcript
  end

  test "message rejects an unknown channel or role" do
    c = Conversation.for(contact: "j@x.com")
    assert_not c.messages.build(channel: "fax", role: "user", body: "x").valid?
    assert_not c.messages.build(channel: "chat", role: "robot", body: "x").valid?
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/models/conversation_test.rb`
Expected: FAIL — no `conversations` table / `Conversation`.

- [ ] **Step 3: Migration**

`db/migrate/20260608000003_create_conversations_and_messages.rb`:

```ruby
class CreateConversationsAndMessages < ActiveRecord::Migration[8.1]
  def change
    create_table :conversations do |t|
      t.string :contact, null: false
      t.string :name
      t.string :last_channel
      t.timestamps
    end
    add_index :conversations, :contact, unique: true

    create_table :messages do |t|
      t.references :conversation, null: false, foreign_key: true
      t.string :channel, null: false
      t.string :role, null: false
      t.text :body
      t.boolean :ai_disclosed, null: false, default: false
      t.timestamps
    end
  end
end
```

- [ ] **Step 4: Mirror into `db/schema.rb`**

Bump the version to `2026_06_08_000003`. Add both tables (place `create_table "conversations"` and `create_table "messages"` after the `create_table "consents"`/`"contracts"` block — order is cosmetic for SQLite):

```ruby
  create_table "conversations", force: :cascade do |t|
    t.string "contact", null: false
    t.datetime "created_at", null: false
    t.string "last_channel"
    t.string "name"
    t.datetime "updated_at", null: false
    t.index ["contact"], name: "index_conversations_on_contact", unique: true
  end

  create_table "messages", force: :cascade do |t|
    t.boolean "ai_disclosed", default: false, null: false
    t.text "body"
    t.string "channel", null: false
    t.integer "conversation_id", null: false
    t.datetime "created_at", null: false
    t.string "role", null: false
    t.datetime "updated_at", null: false
    t.index ["conversation_id"], name: "index_messages_on_conversation_id"
  end
```

And add to the foreign-key list:

```ruby
  add_foreign_key "messages", "conversations"
```

- [ ] **Step 5: Create the models**

`app/models/conversation.rb`:

```ruby
# One durable conversation thread, keyed by a contact (email or phone). Every
# channel (chat/voice/sms/email) reads and writes the same thread, so the agent
# keeps context when a lead switches channels (R4). The brain's thread_id points
# here; this row is the durable record (brain memory is in-process).
class Conversation < ApplicationRecord
  has_many :messages, -> { order(:created_at) }, dependent: :destroy

  validates :contact, presence: true, uniqueness: { case_sensitive: false }
  normalizes :contact, with: ->(c) { Conversation.normalize_contact(c) }

  # Email → lowercased; anything else treated as a phone → keep digits and '+'.
  def self.normalize_contact(raw)
    s = raw.to_s.strip
    s.include?("@") ? s.downcase : s.gsub(/[^\d+]/, "")
  end

  def self.for(contact:, name: nil)
    convo = find_or_create_by!(contact: normalize_contact(contact))
    convo.update!(name: name) if name.present? && convo.name != name
    convo
  end

  def thread_id = "conv-#{id}"

  def append(channel:, role:, body:, ai_disclosed: false)
    msg = messages.create!(channel: channel.to_s, role: role.to_s, body: body.to_s, ai_disclosed: ai_disclosed)
    update_column(:last_channel, channel.to_s)
    msg
  end

  def transcript
    messages.map { |m| "[#{m.channel}] #{m.role}: #{m.body}" }.join("\n")
  end
end
```

`app/models/message.rb`:

```ruby
# One turn in a Conversation, tagged with the channel it arrived/left on and the
# role (user/agent/broker). ai_disclosed records whether AI disclosure was made
# on this turn (voice mandates it).
class Message < ApplicationRecord
  CHANNELS = Channel::CHANNELS
  ROLES = %w[user agent broker].freeze

  belongs_to :conversation

  validates :channel, inclusion: { in: CHANNELS }
  validates :role, inclusion: { in: ROLES }
end
```

- [ ] **Step 6: Run the tests — green**

Run: `bin/rails test test/models/conversation_test.rb`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add db/migrate/20260608000003_create_conversations_and_messages.rb db/schema.rb app/models/conversation.rb app/models/message.rb test/models/conversation_test.rb
git commit -m "feat: Conversation + Message — the durable cross-channel thread"
```

---

## Task 2: AgentReplySummary (answer → thread line)

**Files:**
- Create: `app/services/agent_reply_summary.rb`
- Test: `test/services/agent_reply_summary_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/services/agent_reply_summary_test.rb`:

```ruby
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
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/services/agent_reply_summary_test.rb`
Expected: FAIL — `uninitialized constant AgentReplySummary`.

- [ ] **Step 3: Implement**

`app/services/agent_reply_summary.rb`:

```ruby
# Maps a sidebar answer to a single line for the conversation thread: the full
# orchestrator message when there is one, else a short summary of the card the
# agent rendered. Pure — no IO.
module AgentReplySummary
  module_function

  def line(result: nil, price_check: nil, neighborhood: nil, photo_insight: nil,
           showing: nil, listings: nil, insight_key: nil, query: nil, address: nil)
    about = address.present? ? " for #{address}" : ""
    return result.message if result
    return "Shared a price check#{about}." if price_check
    return "Shared the neighborhood pulse#{about}." if neighborhood || insight_key == "neighborhood"
    return "Shared what the photos show#{about}." if photo_insight || insight_key == "photos"
    return "Shared available tour times#{about}." if showing
    return "Surfaced #{listings.size} matching listings." if listings.present?

    "Answered: #{query}"
  end
end
```

- [ ] **Step 4: Run the tests — green**

Run: `bin/rails test test/services/agent_reply_summary_test.rb`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/agent_reply_summary.rb test/services/agent_reply_summary_test.rb
git commit -m "feat: AgentReplySummary — map a sidebar answer to one thread line"
```

---

## Task 3: Sidebar persists turns into the shared thread

**Files:**
- Modify: `app/models/visitor.rb`
- Modify: `app/controllers/agent/messages_controller.rb`
- Test: `test/controllers/agent/messages_controller_test.rb`

- [ ] **Step 1: Write the failing test**

Add to `services/domain/test/controllers/agent/messages_controller_test.rb`:

```ruby
  test "a signed-in turn persists user + agent messages and reuses the conversation thread_id" do
    post session_path, params: { name: "Bea", email: "bea@example.com" }
    fake = FakeClient.new(grounded)
    use_client(fake) do
      post agent_messages_path, params: { query: "tell me about schools" }, as: :turbo_stream
    end
    convo = Conversation.for(contact: "bea@example.com")
    assert_equal ["tell me about schools", "It's competitively priced."], convo.messages.map(&:body)
    assert_equal %w[user agent], convo.messages.map(&:role)
    assert_equal "conv-#{convo.id}", fake.last_args[:thread_id]   # brain keyed to the durable thread
  end

  test "an anonymous turn persists no conversation" do
    use_client(FakeClient.new(grounded)) do
      post agent_messages_path, params: { query: "hello" }, as: :turbo_stream
    end
    assert_equal 0, Conversation.count
  end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/controllers/agent/messages_controller_test.rb -n "/persists user|anonymous turn persists/"`
Expected: FAIL — no persistence yet.

- [ ] **Step 3: Add `Visitor#conversation`**

In `app/models/visitor.rb`, after `def high_intent?` ... `end` (before `buyer_signals`), add:

```ruby
  # The visitor's durable cross-channel conversation thread (R4), keyed by email.
  def conversation = Conversation.find_by(contact: Conversation.normalize_contact(email))
```

- [ ] **Step 4: Persist turns in the controller**

In `app/controllers/agent/messages_controller.rb#create`, after the `@channel = ...` line add:

```ruby
      @conversation = current_visitor && Conversation.for(contact: current_visitor.email, name: current_visitor.name)
      @conversation&.append(channel: @channel, role: "user", body: @query,
                            ai_disclosed: Channel.mandatory_disclosure?(@channel))
```

After the `if/elsif/else` dispatch block (just before `respond_to do |format|`) add:

```ruby
      if @conversation
        @conversation.append(channel: @channel, role: "agent",
          body: AgentReplySummary.line(result: @result, price_check: @price_check,
            neighborhood: @neighborhood, photo_insight: @photo_insight, showing: @showing,
            listings: @listings, insight_key: @insight_key, query: @query, address: @address),
          ai_disclosed: Channel.mandatory_disclosure?(@channel))
      end
```

Replace the orchestrator line's `thread_id: agent_thread_id` with `thread_id: thread_id`, and replace the `agent_thread_id` private method with:

```ruby
    # The brain thread handle: the durable conversation for a signed-in visitor,
    # else an ephemeral per-session id for anonymous use.
    def thread_id
      @conversation&.thread_id || (session[:agent_thread_id] ||= SecureRandom.uuid)
    end
```

- [ ] **Step 5: Run the tests — green**

Run: `bin/rails test test/controllers/agent/messages_controller_test.rb -n "/persists user|anonymous turn persists/"`
Expected: PASS.

- [ ] **Step 6: Run the whole agent test file (no regressions)**

Run: `bin/rails test test/controllers/agent/messages_controller_test.rb`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add app/models/visitor.rb app/controllers/agent/messages_controller.rb test/controllers/agent/messages_controller_test.rb
git commit -m "feat: sidebar persists every turn into the shared conversation thread"
```

---

## Task 4: Sidebar renders the cross-channel history

**Files:**
- Modify: `app/views/shared/_agent_sidebar.html.erb`
- Test: `test/integration/agent_history_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/integration/agent_history_test.rb`:

```ruby
require "test_helper"

class AgentHistoryTest < ActionDispatch::IntegrationTest
  test "a signed-in visitor sees their prior cross-channel thread in the sidebar" do
    post session_path, params: { name: "Bea", email: "bea@example.com" }
    convo = Conversation.for(contact: "bea@example.com")
    convo.append(channel: "chat", role: "user", body: "what's it worth?")
    convo.append(channel: "sms", role: "agent", body: "About $610k.")

    get buyer_listings_path
    assert_response :success
    assert_match "what's it worth?", @response.body
    assert_match "About $610k.", @response.body
    assert_match(/sms/, @response.body)   # the channel tag is shown
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/integration/agent_history_test.rb`
Expected: FAIL — history not rendered.

- [ ] **Step 3: Render history in the sidebar**

In `app/views/shared/_agent_sidebar.html.erb`, replace the static greeting block:

```erb
  <div id="agent-messages" class="agent-messages" data-agent-sidebar-target="messages">
    <div class="agent-msg agent-msg--bot">
      <div class="agent-bubble">
        Hi — I'm Atlas. Ask me about a neighborhood, a price, or whether a home is a good deal.
        Open a listing and I'll know which home you mean.
      </div>
    </div>
  </div>
```

with:

```erb
  <div id="agent-messages" class="agent-messages" data-agent-sidebar-target="messages">
    <% history = (current_visitor&.conversation&.messages || []) %>
    <% if history.any? %>
      <% history.each do |m| %>
        <div class="agent-msg agent-msg--<%= m.role == "user" ? "user" : "bot" %>">
          <div class="agent-bubble">
            <% if m.channel != "chat" %><span class="mk-badge agent-channel"><%= m.channel %></span><% end %>
            <%= m.body %>
          </div>
        </div>
      <% end %>
    <% else %>
      <div class="agent-msg agent-msg--bot">
        <div class="agent-bubble">
          Hi — I'm Atlas. Ask me about a neighborhood, a price, or whether a home is a good deal.
          Open a listing and I'll know which home you mean.
        </div>
      </div>
    <% end %>
  </div>
```

- [ ] **Step 4: Run the test — green**

Run: `bin/rails test test/integration/agent_history_test.rb`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/views/shared/_agent_sidebar.html.erb test/integration/agent_history_test.rb
git commit -m "feat: sidebar shows the persisted cross-channel history"
```

---

## Task 5: Real Twilio + SendGrid outbound adapters

**Files:**
- Modify: `app/services/channel_transport.rb`
- Test: `test/services/channel_transport_test.rb`

- [ ] **Step 1: Write the failing test**

Add to `services/domain/test/services/channel_transport_test.rb`:

```ruby
  test "TwilioSms posts to the Messages API when configured (no live HTTP in test)" do
    ENV["TWILIO_ACCOUNT_SID"] = "AC123"; ENV["TWILIO_AUTH_TOKEN"] = "tok"; ENV["TWILIO_FROM"] = "+15120000000"
    captured = {}
    ChannelTransport.stub(:http_post_form, ->(uri, fields, **kw) { captured[:uri] = uri.to_s; captured[:fields] = fields; "SM1" }) do
      r = ChannelTransport::TwilioSms.new.deliver(to: "+15125550100", body: "hi there")
      assert_equal "sent", r.status
      assert_equal "twilio", r.provider
    end
    assert_match %r{Accounts/AC123/Messages\.json}, captured[:uri]
    assert_equal "hi there", captured[:fields]["Body"]
    assert_equal "+15125550100", captured[:fields]["To"]
  ensure
    %w[TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_FROM].each { |k| ENV.delete(k) }
  end

  test "SendgridEmail posts to the v3 send API when configured" do
    ENV["SENDGRID_API_KEY"] = "SG.x"; ENV["SENDGRID_FROM"] = "atlas@example.com"
    captured = {}
    ChannelTransport.stub(:http_post_json, ->(uri, payload, **kw) { captured[:uri] = uri.to_s; captured[:payload] = payload; "OK" }) do
      r = ChannelTransport::SendgridEmail.new.deliver(to: "buyer@example.com", body: "your update")
      assert_equal "sent", r.status
    end
    assert_match %r{/v3/mail/send}, captured[:uri]
    assert_equal "buyer@example.com", captured[:payload][:personalizations][0][:to][0][:email]
  ensure
    %w[SENDGRID_API_KEY SENDGRID_FROM].each { |k| ENV.delete(k) }
  end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/services/channel_transport_test.rb -n "/Messages API|v3 send/"`
Expected: FAIL — `NotImplementedError` / no `http_post_form`.

- [ ] **Step 3: Implement the adapters + http helpers**

In `app/services/channel_transport.rb`, add `require "net/http"` and `require "json"` at the top. Replace the `TwilioSms#deliver` body:

```ruby
    def deliver(to:, body:)
      sid = ENV["TWILIO_ACCOUNT_SID"]; token = ENV["TWILIO_AUTH_TOKEN"]; from = ENV["TWILIO_FROM"]
      ChannelTransport.http_post_form(
        URI("https://api.twilio.com/2010-04-01/Accounts/#{sid}/Messages.json"),
        { "From" => from.to_s, "To" => to.to_s, "Body" => body.to_s },
        basic_auth: [sid, token]
      )
      Result.new(status: "sent", provider: "twilio", note: "delivered via Twilio")
    rescue StandardError => e
      Result.new(status: "error", provider: "twilio", note: e.message)
    end
```

Replace the `SendgridEmail#deliver` body:

```ruby
    def deliver(to:, body:)
      payload = {
        personalizations: [{ to: [{ email: to.to_s }] }],
        from: { email: ENV["SENDGRID_FROM"].to_s }, subject: "Your Atlas update",
        content: [{ type: "text/plain", value: body.to_s }]
      }
      ChannelTransport.http_post_json(URI("https://api.sendgrid.com/v3/mail/send"), payload,
                                      bearer: ENV["SENDGRID_API_KEY"].to_s)
      Result.new(status: "sent", provider: "sendgrid", note: "delivered via SendGrid")
    rescue StandardError => e
      Result.new(status: "error", provider: "sendgrid", note: e.message)
    end
```

Add the http helpers as `module_function`s (after the existing `out_of_band?`):

```ruby
  # Minimal HTTP posters (stubbed in tests). Only ever called when a provider is
  # configured, so the demo (no keys) never constructs them.
  def http_post_form(uri, fields, basic_auth: nil)
    req = Net::HTTP::Post.new(uri)
    req.set_form_data(fields)
    req.basic_auth(*basic_auth) if basic_auth
    _http_run(uri, req)
  end

  def http_post_json(uri, payload, bearer:)
    req = Net::HTTP::Post.new(uri)
    req["Authorization"] = "Bearer #{bearer}"
    req["Content-Type"] = "application/json"
    req.body = payload.to_json
    _http_run(uri, req)
  end

  def _http_run(uri, req)
    Net::HTTP.start(uri.host, uri.port, use_ssl: true, open_timeout: 5, read_timeout: 10) do |http|
      http.request(req)
    end
  end
```

- [ ] **Step 4: Run the tests — green**

Run: `bin/rails test test/services/channel_transport_test.rb`
Expected: PASS (existing simulated/out-of-band tests + the 2 new), 0 failures.

- [ ] **Step 5: Commit**

```bash
git add app/services/channel_transport.rb test/services/channel_transport_test.rb
git commit -m "feat: real Twilio SMS + SendGrid email outbound adapters (ENV-gated)"
```

---

## Task 6: InboundTurn pipeline

**Files:**
- Create: `app/services/inbound_turn.rb`
- Test: `test/services/inbound_turn_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/services/inbound_turn_test.rb`:

```ruby
require "test_helper"

class InboundTurnTest < ActiveSupport::TestCase
  class OkBrain
    def orchestrate(**) = Struct.new(:message).new("Happy to help — here's a quick answer.")
  end
  class DeadBrain
    def orchestrate(**) = raise("brain down")
  end

  test "appends the inbound turn, orchestrates, appends the reply" do
    r = InboundTurn.call(contact: "+15125550100", channel: "sms", body: "is 9 Demo St a deal?", client: OkBrain.new)
    assert_equal "Happy to help — here's a quick answer.", r.reply
    assert_equal %w[user agent], r.conversation.messages.map(&:role)
    assert_equal %w[sms sms], r.conversation.messages.map(&:channel)
  end

  test "brain-down still appends a fallback reply" do
    r = InboundTurn.call(contact: "buyer@x.com", channel: "email", body: "hi", client: DeadBrain.new)
    assert_match(/broker/i, r.reply)
    assert_equal 2, r.conversation.messages.count
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/services/inbound_turn_test.rb`
Expected: FAIL — `uninitialized constant InboundTurn`.

- [ ] **Step 3: Implement**

`app/services/inbound_turn.rb`:

```ruby
# The single inbound pipeline shared by SMS / email / voice (R4): find-or-create
# the contact's Conversation, append the inbound turn, run one orchestrator turn
# keyed to the durable thread, append the reply, and return it. Brain-down yields
# a friendly fallback so a webhook never dead-ends.
class InboundTurn
  FALLBACK = "Thanks for reaching out — a licensed Atlas broker will follow up shortly.".freeze

  Result = Struct.new(:conversation, :reply, keyword_init: true)

  def self.call(contact:, channel:, body:, name: nil, client: BrainConversationClient.new)
    convo = Conversation.for(contact: contact, name: name)
    disclosed = Channel.mandatory_disclosure?(channel)
    convo.append(channel: channel, role: "user", body: body, ai_disclosed: disclosed)

    reply =
      begin
        res = client.orchestrate(query: body.to_s, thread_id: convo.thread_id)
        res.message.presence || FALLBACK
      rescue StandardError => e
        Rails.logger.warn("[inbound] orchestrate failed: #{e.class}: #{e.message}")
        FALLBACK
      end

    convo.append(channel: channel, role: "agent", body: reply, ai_disclosed: disclosed)
    Result.new(conversation: convo, reply: reply)
  end
end
```

- [ ] **Step 4: Run the tests — green**

Run: `bin/rails test test/services/inbound_turn_test.rb`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/inbound_turn.rb test/services/inbound_turn_test.rb
git commit -m "feat: InboundTurn — append/orchestrate/append for inbound channels"
```

---

## Task 7: Inbound SMS + Email webhooks

**Files:**
- Create: `app/controllers/inbound/base_controller.rb`, `sms_controller.rb`, `email_controller.rb`
- Modify: `config/routes.rb`
- Test: `test/controllers/inbound/webhooks_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/controllers/inbound/webhooks_test.rb`:

```ruby
require "test_helper"

class Inbound::WebhooksTest < ActionDispatch::IntegrationTest
  class FakeBrain
    def orchestrate(**) = Struct.new(:message).new("Here's what I found.")
  end

  setup { ENV["INBOUND_WEBHOOK_TOKEN"] = "secret" }
  teardown { ENV.delete("INBOUND_WEBHOOK_TOKEN") }

  test "inbound SMS appends to the thread and replies with TwiML" do
    BrainConversationClient.stub(:new, FakeBrain.new) do
      post inbound_sms_path, params: { token: "secret", From: "+15125550100", Body: "is it a deal?" }
    end
    assert_response :success
    assert_match %r{<Response><Message>Here's what I found\.</Message></Response>}, @response.body
    assert_equal 2, Conversation.for(contact: "+15125550100").messages.count
  end

  test "inbound email appends and triggers a (simulated) reply" do
    BrainConversationClient.stub(:new, FakeBrain.new) do
      post inbound_email_path, params: { token: "secret", from: "buyer@x.com", text: "hello" }
    end
    assert_response :success
    assert_equal 2, Conversation.for(contact: "buyer@x.com").messages.count
  end

  test "a bad token is rejected" do
    post inbound_sms_path, params: { token: "wrong", From: "+1", Body: "x" }
    assert_response :unauthorized
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/controllers/inbound/webhooks_test.rb`
Expected: FAIL — no `inbound_sms_path`.

- [ ] **Step 3: Add the routes**

In `config/routes.rb`, after the `namespace :agent do ... end` block add:

```ruby
  # Inbound provider webhooks (Twilio SMS, SendGrid Inbound Parse, voice relay).
  # Guarded by INBOUND_WEBHOOK_TOKEN; off until configured.
  namespace :inbound do
    post "sms"
    post "email"
    post "voice"
  end
```

- [ ] **Step 4: Implement the controllers**

`app/controllers/inbound/base_controller.rb`:

```ruby
module Inbound
  # Base for provider webhooks. CSRF-exempt (providers can't carry our token) and
  # guarded by a shared secret. Full Twilio-signature / SendGrid validation is the
  # documented production seam.
  class BaseController < ActionController::Base
    skip_forgery_protection
    before_action :verify_token

    private

    def verify_token
      expected = ENV["INBOUND_WEBHOOK_TOKEN"].to_s
      given = (params[:token].presence || request.headers["X-Webhook-Token"]).to_s
      return if expected.present? && ActiveSupport::SecurityUtils.secure_compare(given, expected)

      head :unauthorized
    end
  end
end
```

`app/controllers/inbound/sms_controller.rb`:

```ruby
module Inbound
  # Twilio inbound SMS webhook. Appends to the sender's thread, orchestrates, and
  # replies with TwiML (Twilio relays it as the SMS reply — no outbound call).
  class SmsController < BaseController
    def create
      result = InboundTurn.call(contact: params[:From], channel: "sms", body: params[:Body].to_s)
      twiml = %(<?xml version="1.0" encoding="UTF-8"?><Response><Message>#{ERB::Util.html_escape(result.reply)}</Message></Response>)
      render xml: twiml
    end
  end
end
```

`app/controllers/inbound/email_controller.rb`:

```ruby
module Inbound
  # SendGrid Inbound Parse webhook. Appends to the sender's thread, orchestrates,
  # and emails the reply (simulated until SendGrid is configured).
  class EmailController < BaseController
    def create
      result = InboundTurn.call(contact: params[:from], channel: "email", body: params[:text].to_s)
      ChannelTransport.deliver(channel: "email", to: params[:from].to_s, body: result.reply)
      head :ok
    end
  end
end
```

- [ ] **Step 5: Run the tests — green**

Run: `bin/rails test test/controllers/inbound/webhooks_test.rb`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add app/controllers/inbound/base_controller.rb app/controllers/inbound/sms_controller.rb app/controllers/inbound/email_controller.rb config/routes.rb test/controllers/inbound/webhooks_test.rb
git commit -m "feat: inbound SMS + email webhooks join the shared thread"
```

---

## Task 8: Inbound voice endpoint

**Files:**
- Create: `app/controllers/inbound/voice_controller.rb`
- Test: `test/controllers/inbound/voice_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/controllers/inbound/voice_test.rb`:

```ruby
require "test_helper"

class Inbound::VoiceTest < ActionDispatch::IntegrationTest
  class FakeBrain
    def orchestrate(**) = Struct.new(:message).new("Spoken answer.")
  end

  setup { ENV["INBOUND_WEBHOOK_TOKEN"] = "secret" }
  teardown { ENV.delete("INBOUND_WEBHOOK_TOKEN") }

  test "voice relay appends a voice turn and returns the reply as JSON" do
    BrainConversationClient.stub(:new, FakeBrain.new) do
      post inbound_voice_path, params: { token: "secret", contact: "voice-abc", text: "what's my home worth?" }
    end
    assert_response :success
    assert_equal "Spoken answer.", JSON.parse(@response.body)["reply"]
    convo = Conversation.for(contact: "voice-abc")
    assert_equal %w[voice voice], convo.messages.map(&:channel)
    assert convo.messages.first.ai_disclosed   # voice mandates disclosure
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/controllers/inbound/voice_test.rb`
Expected: FAIL — no `Inbound::VoiceController`.

- [ ] **Step 3: Implement**

`app/controllers/inbound/voice_controller.rb`:

```ruby
module Inbound
  # Voice relay: the Go voice service posts each turn here so a phone call joins
  # the same durable thread (R4). Returns the agent reply for the service to speak.
  class VoiceController < BaseController
    def create
      result = InboundTurn.call(contact: params[:contact], channel: "voice", body: params[:text].to_s)
      render json: { reply: result.reply }
    end
  end
end
```

- [ ] **Step 4: Run the test — green**

Run: `bin/rails test test/controllers/inbound/voice_test.rb`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/controllers/inbound/voice_controller.rb test/controllers/inbound/voice_test.rb
git commit -m "feat: inbound voice relay endpoint for the shared thread"
```

---

## Task 9: Broker cross-channel transcript on handoff

**Files:**
- Modify: `app/models/visitor.rb`
- Test: `test/models/visitor_test.rb`

- [ ] **Step 1: Write the failing test**

Add to `services/domain/test/models/visitor_test.rb`:

```ruby
  test "a handoff carries the visitor's cross-channel transcript" do
    v = Visitor.sign_in(name: "Bea", email: "bea@example.com")
    convo = Conversation.for(contact: "bea@example.com")
    convo.append(channel: "chat", role: "user", body: "is 9 Demo St a deal?")
    convo.append(channel: "sms", role: "agent", body: "Looks well-priced.")

    v.record_buyer_profile(pre_approved: "yes", move_timeline_days: 20, budget_cents: nil)

    packet = HandoffPacket.queue.first
    assert_includes packet.transcript, "[chat] user: is 9 Demo St a deal?"
    assert_includes packet.transcript, "[sms] agent: Looks well-priced."
  end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/models/visitor_test.rb -n "/cross-channel transcript/"`
Expected: FAIL — `transcript` is nil.

- [ ] **Step 3: Populate the transcript**

In `app/models/visitor.rb#route_to_broker`, change the `EnqueueHandoff.call(...)` to pass the transcript:

```ruby
    EnqueueHandoff.call(
      lead: lead,
      trigger: "high_intent",
      reason: triage.reason,
      transcript: conversation&.transcript,
      recommended_action: "Engage high-intent #{side} (#{name}) — #{triage.signals_used.join(', ')}"
    )
```

- [ ] **Step 4: Run the test — green**

Run: `bin/rails test test/models/visitor_test.rb -n "/cross-channel transcript/"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/visitor.rb test/models/visitor_test.rb
git commit -m "feat: broker handoff carries the cross-channel transcript"
```

---

## Task 10: Wire the Go voice service to the shared thread

**Files:**
- Create: `services/voice/relay.go`
- Modify: `services/voice/main.go`
- Test: `services/voice/relay_test.go`

- [ ] **Step 1: Confirm the agent role + read AppendTurn**

Run: `grep -n "RoleSeller\|RoleAgent\|Role(" services/voice/session.go`
Note the existing role constants. If there is no agent role, add `RoleAgent Role = "agent"` next to `RoleSeller` in `session.go`.

- [ ] **Step 2: Write the failing test**

`services/voice/relay_test.go`:

```go
package main

import "testing"

type fakeRelay struct{ got string }

func (f *fakeRelay) Reply(contact, text string) (string, error) {
	f.got = text
	return "spoken reply", nil
}

func TestHandleMessageAppendsRelayReply(t *testing.T) {
	relay := &fakeRelay{}
	srv := &server{manager: NewManager(), relay: relay}
	sess := srv.manager.Start()
	srv.manager.AppendTurn(sess.ID, RoleSeller, "hello", nil)

	reply, ok := srv.relayReply(sess.ID, "what's my home worth?")
	if !ok || reply != "spoken reply" {
		t.Fatalf("expected relay reply, got %q ok=%v", reply, ok)
	}
	if relay.got != "what's my home worth?" {
		t.Fatalf("relay saw %q", relay.got)
	}
	got, _ := srv.manager.Get(sess.ID)
	last := got.Thread[len(got.Thread)-1]
	if last.Role != RoleAgent || last.Text != "spoken reply" {
		t.Fatalf("agent turn not appended: %+v", last)
	}
}
```

> If `Manager` has no `Get(id)`, use the `(Session, bool)` returned by `AppendTurn` in the helper instead and assert on that; adjust the test to the real accessor found in `session.go`.

- [ ] **Step 3: Run it — fail**

Run: `cd "/Users/rikki/Desktop/AI Real Estate Agent/.claude/worktrees/brain-pillars" && go test ./services/voice/... 2>&1 | tail -10`
Expected: FAIL — `server` has no `relay` / `relayReply`.

- [ ] **Step 4: Implement the relay**

`services/voice/relay.go`:

```go
package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"time"
)

// ThreadRelay forwards a turn to the Rails shared conversation thread and returns
// the agent's reply. Nil when DOMAIN_URL is unset (voice stays standalone).
type ThreadRelay interface {
	Reply(contact, text string) (string, error)
}

// HTTPRelay posts to <DOMAIN_URL>/inbound/voice with the shared webhook token.
type HTTPRelay struct {
	URL    string
	Token  string
	Client *http.Client
}

func (h HTTPRelay) Reply(contact, text string) (string, error) {
	body, _ := json.Marshal(map[string]string{"contact": contact, "text": text, "token": h.Token})
	client := h.Client
	if client == nil {
		client = &http.Client{Timeout: 10 * time.Second}
	}
	resp, err := client.Post(h.URL+"/inbound/voice", "application/json", bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var out struct {
		Reply string `json:"reply"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", err
	}
	return out.Reply, nil
}
```

- [ ] **Step 5: Wire it into the server**

In `services/voice/main.go`, add a `relay ThreadRelay` field to `server`, a `relayReply` helper, and call it from `handleMessage`. Add to the `server` struct:

```go
type server struct {
	manager *Manager
	relay   ThreadRelay
}
```

Add the helper:

```go
// relayReply forwards the turn to the shared thread (if a relay is configured)
// and appends the agent's reply to the session. Returns ("", false) when there
// is no relay or the call fails (voice degrades to standalone).
func (s *server) relayReply(sessionID, text string) (string, bool) {
	if s.relay == nil {
		return "", false
	}
	reply, err := s.relay.Reply("voice-"+sessionID, text)
	if err != nil || reply == "" {
		return "", false
	}
	s.manager.AppendTurn(sessionID, RoleAgent, reply, nil)
	return reply, true
}
```

In `handleMessage`, after `sess, found := s.manager.AppendTurn(id, RoleSeller, req.Text, req.Fields)` and the `!found` guard, add:

```go
	if reply, ok := s.relayReply(id, req.Text); ok {
		sess, _ = s.manager.AppendTurn(id, RoleSeller, "", nil) // refresh
		_ = reply
	}
```

> Simpler: re-fetch the session after the relay append so the response includes the agent turn. If `AppendTurn` with an empty turn is undesirable, use the `(Session, bool)` already returned by `relayReply`'s internal `AppendTurn` by having `relayReply` return the updated `Session` too. Keep the response shape (`messageResponse`) unchanged.

Where `server` is constructed (in `main()`), set the relay from env:

```go
	srv := &server{manager: NewManager()}
	if url := os.Getenv("DOMAIN_URL"); url != "" {
		srv.relay = HTTPRelay{URL: url, Token: os.Getenv("INBOUND_WEBHOOK_TOKEN")}
	}
```

(add `"os"` to imports if not present.)

- [ ] **Step 6: Run the Go tests — green**

Run: `cd "/Users/rikki/Desktop/AI Real Estate Agent/.claude/worktrees/brain-pillars" && go test ./services/voice/... 2>&1 | tail -10`
Expected: PASS (the existing voice tests + the new relay test).

- [ ] **Step 7: Commit**

```bash
git add services/voice/relay.go services/voice/main.go services/voice/session.go services/voice/relay_test.go
git commit -m "feat(voice): relay each turn into the Rails shared thread"
```

---

## Task 11: Docs + full suites + final commit

**Files:**
- Modify: `services/domain/README.md`, root `README.md`, `deploy/fly/DEPLOY.md`, spec status.

- [ ] **Step 1: Full Rails suite**

Run: `cd services/domain && eval "$(rbenv init - zsh)" && bin/rails test 2>&1 | tail -4`
Expected: prior 304 + new, 0 failures. Record the count.

- [ ] **Step 2: Go build + voice tests**

Run: `cd "/Users/rikki/Desktop/AI Real Estate Agent/.claude/worktrees/brain-pillars" && go build ./... && go test ./services/voice/... 2>&1 | tail -4`
Expected: clean build, voice tests pass.

- [ ] **Step 3: `services/domain/README.md`** — add a subsection:

```markdown
## Omnichannel — one shared thread (R4)

Every channel (chat / voice / sms / email) reads and writes one persisted
`Conversation` (keyed by contact); each turn is a channel-tagged `Message`. The
Ask Atlas sidebar persists a signed-in visitor's turns and renders the
cross-channel history, and passes `conversation.thread_id` to the brain so context
carries across channels. Real `TwilioSms` / `SendgridEmail` adapters send when
`TWILIO_*` / `SENDGRID_*` are set; otherwise the `Simulated` transport keeps the
demo external-call-free. Inbound webhooks (`/inbound/sms`, `/inbound/email`,
`/inbound/voice`, guarded by `INBOUND_WEBHOOK_TOKEN`) append to the same thread,
orchestrate, and reply on the channel. A handoff carries the full cross-channel
transcript to the broker dashboard.
```

- [ ] **Step 4: root `README.md`** — set the Voice/omnichannel capability row to live (one shared thread; real adapters ENV-gated; inbound webhooks) and bump the Rails test count.

- [ ] **Step 5: `deploy/fly/DEPLOY.md`** — document the new optional env on `are-domain`: `TWILIO_FROM`, `SENDGRID_FROM`, `INBOUND_WEBHOOK_TOKEN`; and on `are-voice`: `DOMAIN_URL` + `INBOUND_WEBHOOK_TOKEN`. Note inbound is off until the token is set.

- [ ] **Step 6: Flip the spec status** to `Status: Implemented`.

- [ ] **Step 7: Final commit**

```bash
git add services/domain/README.md README.md deploy/fly/DEPLOY.md docs/superpowers/specs/2026-06-08-omnichannel-design.md
git commit -m "docs: omnichannel (R4) — shared cross-channel thread"
```

---

## Self-Review

**Spec coverage:**
- A. Conversation + Message → Task 1. ✓
- B. Sidebar joins/persists + renders history → Tasks 2, 3, 4. ✓
- C. Real Twilio/SendGrid adapters → Task 5. ✓
- D. Inbound webhooks (SMS/email) + token guard → Tasks 6, 7. ✓
- E. Broker transcript → Task 9. ✓
- F. Voice (inbound endpoint + Go relay) → Tasks 8, 10. ✓
- Docs + invariants → Task 11; demo stays simulated (adapters only build HTTP when configured); disclosure recorded per message; no proto change. ✓

**Placeholder scan:** none — all code concrete. (Task 10 Step 5 includes a clearly-marked "simpler" note pointing at the real accessor in `session.go`; the implementer confirms the role/accessor names in Step 1 — this is verification, not a placeholder.)

**Type/name consistency:** `Conversation.for/.normalize_contact/#thread_id/#append/#transcript`, `Message::CHANNELS/ROLES`, `Visitor#conversation`, `thread_id` (controller), `AgentReplySummary.line(...)` kwargs match the controller call, `InboundTurn.call(contact:, channel:, body:, name:, client:)` + `Result(conversation, reply)` consumed by all three inbound controllers, `ChannelTransport.http_post_form/http_post_json`, routes `inbound_sms_path/inbound_email_path/inbound_voice_path`, Go `server.relay/relayReply` + `HTTPRelay`. Migration version `2026_06_08_000003`.

**Implementer notes:**
- Task 3 inserts the agent-turn append after the whole if/elsif/else dispatch (so every answer type is summarized). The `thread_id` method replaces `agent_thread_id`; update the one call site on the orchestrator line.
- Inbound controller tests stub `BrainConversationClient.new` (not the agent controller's `client_factory`).
- Task 10 is the only Go change and is cuttable if it balloons — Tasks 1–9 deliver the full Rails omnichannel thread on their own.
