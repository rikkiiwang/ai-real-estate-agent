# Closing Orchestration Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing Python `ClosingOrchestrator` into the live flow — exposed over a new `Closer.RecordMilestone` RPC, driven from the broker dashboard (and auto-triggered by completed inspections), with Rails owning state/idempotency/order, simulated+audited counterparty pings, and a buyer-visible read-only tracker.

**Architecture:** The brain stays stateless: `Closer.RecordMilestone` runs `ClosingOrchestrator.record(met=True)` with a capturing sink and returns the ping (counterparty + message). Rails owns the deal (the signed `Offer`), persists each met milestone in `ClosingMilestone` (unique per offer+milestone), enforces canonical order, and on brain-down falls back to a local routing copy marked `pending`. Every milestone writes an append-only `AuditEvent`.

**Tech Stack:** Python (grpc) brain, Rails 8.1 (Hotwire), protobuf (Go/Python/Ruby stubs), Minitest, pytest, SQLite (Rails test). rbenv Ruby 3.3.11.

**Invariants:** no external paid calls (RecordMilestone is an internal brain RPC on a broker action) · pings simulated + audited + honestly labeled · append-only audit per milestone · Rails owns state, brain is stateless.

**Spec:** `docs/superpowers/specs/2026-06-08-closing-orchestration-design.md`

**Shell setup (Rails):**
```bash
cd "/Users/rikki/Desktop/AI Real Estate Agent/services/domain"
eval "$(rbenv init - zsh)"
```
Rails suite: `bin/rails test`. Brain suite: `cd services/brain && PYTHONPATH=src python3 -m pytest -q` (if `grpc`/`grpc_tools` import fails, use `/opt/anaconda3/bin/python3`). Proto regen: `make proto PYTHON=/opt/anaconda3/bin/python3` from repo root.

> Work from the MAIN repo paths shown. We are on branch `feat/brain-vision` (already == main tip).

---

## File Structure

- `proto/realestate/v1/realestate.proto` — **modify**: add `RecordMilestone` RPC + 2 messages to `Closer`.
- Generated stubs (Go/Python/Ruby) — **regenerate** via `make proto`.
- `services/brain/src/brain/closer_service.py` — **modify**: `RecordMilestone` + `_CapturingSink`.
- `services/brain/tests/test_closer_servicer.py` — **create**.
- `services/domain/app/models/closing_milestone.rb` — **create**.
- `services/domain/app/models/offer.rb` — **modify**: closing helpers.
- `services/domain/app/models/appointment.rb` — **modify**: `belongs_to :offer` + `resolve_offer`.
- `services/domain/app/services/closing_client.rb` — **create**.
- `services/domain/app/services/closing_orchestration.rb` — **create**.
- `services/domain/app/controllers/broker/closings_controller.rb` — **create**.
- `services/domain/app/controllers/broker/appointments_controller.rb` — **modify**: `complete`.
- `services/domain/app/controllers/broker/dashboard_controller.rb` — **modify**: `@closing_deals`.
- `services/domain/app/views/shared/_closing_tracker.html.erb` — **create** (shared read-only).
- `services/domain/app/views/broker/dashboard/show.html.erb` — **modify**: closing panel.
- `services/domain/app/views/consumer/contracts/show.html.erb` — **modify**: buyer tracker.
- `services/domain/config/routes.rb` — **modify**: broker offers `record_milestone`, appointments `complete`.
- 2 migrations + `db/schema.rb`.
- Tests under `services/domain/test/...`.
- Docs: root `README.md`, `services/domain/README.md`, spec status.

---

## Task 1: Proto — add `Closer.RecordMilestone` + regenerate stubs

**Files:**
- Modify: `proto/realestate/v1/realestate.proto:228-230`
- Regenerate: Go/Python/Ruby stubs

- [ ] **Step 1: Add the RPC + messages**

In `proto/realestate/v1/realestate.proto`, change the `Closer` service block:

```proto
service Closer {
  rpc GenerateContract(GenerateContractRequest) returns (GenerateContractResponse);
  rpc RecordMilestone(RecordMilestoneRequest) returns (RecordMilestoneResponse);
}
```

And add, immediately after the `GenerateContractResponse` message:

```proto
message RecordMilestoneRequest {
  string deal_id = 1;
  string milestone = 2;   // inspection_cleared | earnest_deposited | title_cleared | funded
}
message RecordMilestoneResponse {
  bool pinged = 1;
  string counterparty = 2;   // escrow | title | lender
  string message = 3;
}
```

- [ ] **Step 2: Regenerate all stubs**

Run (from repo root): `make proto PYTHON=/opt/anaconda3/bin/python3`
Expected: regenerates Go (`genproto`), Python (`services/brain/src/genproto`), and Ruby (`services/domain/lib`) — exit 0.

- [ ] **Step 3: Verify the generated symbols exist**

Run: `cd services/brain && PYTHONPATH=src python3 -c "from genproto.realestate.v1 import realestate_pb2 as pb; print(pb.RecordMilestoneRequest, pb.RecordMilestoneResponse)"`
Expected: prints both message classes (no ImportError).

Run (Ruby): `cd services/domain && eval "$(rbenv init - zsh)" && ruby -e "require './config/environment'; puts Realestate::V1::RecordMilestoneRequest.new(deal_id: 'x', milestone: 'funded').inspect"`
Expected: prints a populated message (the Ruby stub regenerated).

- [ ] **Step 4: Verify Go still builds (server impls embed Unimplemented, so adding a method is safe)**

Run: `go build ./... 2>&1 | tail -5`
Expected: no output (clean build).

- [ ] **Step 5: Commit**

```bash
git add proto/realestate/v1/realestate.proto genproto services/brain/src/genproto services/domain/lib
git commit -m "feat(proto): add Closer.RecordMilestone RPC + messages"
```

---

## Task 2: Brain — `CloserServicer.RecordMilestone`

**Files:**
- Modify: `services/brain/src/brain/closer_service.py`
- Test: `services/brain/tests/test_closer_servicer.py`

- [ ] **Step 1: Write the failing test**

`services/brain/tests/test_closer_servicer.py`:

```python
import grpc
import pytest

from genproto.realestate.v1 import realestate_pb2 as pb
from brain.closer_service import CloserServicer


class _Ctx:
    """Minimal gRPC context: abort records + raises (mirrors real abort)."""
    def __init__(self):
        self.code = None
        self.details = None

    def abort(self, code, details):
        self.code = code
        self.details = details
        raise RuntimeError("aborted")


def test_record_milestone_routes_earnest_to_escrow():
    resp = CloserServicer().RecordMilestone(
        pb.RecordMilestoneRequest(deal_id="deal-7", milestone="earnest_deposited"), _Ctx()
    )
    assert resp.pinged is True
    assert resp.counterparty == "escrow"
    assert "deal-7" in resp.message


def test_record_milestone_routes_funded_to_lender():
    resp = CloserServicer().RecordMilestone(
        pb.RecordMilestoneRequest(deal_id="deal-7", milestone="funded"), _Ctx()
    )
    assert resp.counterparty == "lender"


def test_record_milestone_rejects_unknown_milestone():
    ctx = _Ctx()
    with pytest.raises(RuntimeError):
        CloserServicer().RecordMilestone(
            pb.RecordMilestoneRequest(deal_id="deal-7", milestone="nope"), ctx
        )
    assert ctx.code == grpc.StatusCode.INVALID_ARGUMENT
```

- [ ] **Step 2: Run it — fail**

Run: `cd services/brain && PYTHONPATH=src python3 -m pytest tests/test_closer_servicer.py -q`
Expected: FAIL — `CloserServicer` has no `RecordMilestone`.

- [ ] **Step 3: Implement the servicer method**

In `services/brain/src/brain/closer_service.py`, add to the imports (after the existing `import json`/`import logging`):

```python
import grpc

from brain.orchestrator.closing import (
    ClosingOrchestrator,
    Counterparty,
    CounterpartyPing,
    Milestone,
)
```

Add these module-level helpers (after `logger = logging.getLogger(__name__)`):

```python
# Human-readable action per milestone, for the counterparty ping message.
_MILESTONE_ACTION = {
    Milestone.INSPECTION_CLEARED: "inspection cleared — releasing contingency",
    Milestone.EARNEST_DEPOSITED: "earnest-money deposit triggered",
    Milestone.TITLE_CLEARED: "title cleared — preparing settlement",
    Milestone.FUNDED: "loan funded — ready to disburse",
}


class _CapturingSink:
    """A CounterpartySink that captures the single emitted ping for the RPC."""

    def __init__(self) -> None:
        self.ping_obj: CounterpartyPing | None = None

    def ping(self, ping: CounterpartyPing) -> None:
        self.ping_obj = ping


def _ping_message(milestone: Milestone, counterparty: Counterparty, deal_id: str) -> str:
    return f"Notified {counterparty.value}: {_MILESTONE_ACTION[milestone]} for {deal_id}."
```

Add the method inside `class CloserServicer` (after `GenerateContract`):

```python
    def RecordMilestone(self, request, context):  # noqa: N802 (gRPC naming)
        try:
            milestone = Milestone(request.milestone)
        except ValueError:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"unknown milestone: {request.milestone!r}",
            )
            return pb.RecordMilestoneResponse()  # unreachable (abort raises)

        sink = _CapturingSink()
        orchestrator = ClosingOrchestrator(deal_id=request.deal_id, sink=sink)
        pinged = orchestrator.record(milestone, met=True)
        counterparty = sink.ping_obj.counterparty if sink.ping_obj else None
        return pb.RecordMilestoneResponse(
            pinged=pinged,
            counterparty=counterparty.value if counterparty else "",
            message=_ping_message(milestone, counterparty, request.deal_id) if counterparty else "",
        )
```

- [ ] **Step 4: Run the tests — green**

Run: `cd services/brain && PYTHONPATH=src python3 -m pytest tests/test_closer_servicer.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/brain/src/brain/closer_service.py services/brain/tests/test_closer_servicer.py
git commit -m "feat(brain): Closer.RecordMilestone routes milestone pings via the orchestrator"
```

---

## Task 3: Rails — `ClosingMilestone` model + `Offer` helpers

**Files:**
- Create: `db/migrate/20260608000001_create_closing_milestones.rb`
- Modify: `db/schema.rb`
- Create: `app/models/closing_milestone.rb`
- Modify: `app/models/offer.rb`
- Test: `test/models/closing_milestone_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/models/closing_milestone_test.rb`:

```ruby
require "test_helper"

class ClosingMilestoneTest < ActiveSupport::TestCase
  def offer
    lead = Lead.create!(side: "buyer", address: "1 A St", contact: "b@x.com", intent: "high")
    Offer.create!(lead: lead, side: "buyer", status: "signed")
  end

  test "milestone is unique per offer" do
    o = offer
    o.closing_milestones.create!(milestone: "inspection_cleared", ping_status: "simulated", recorded_at: Time.current)
    dup = o.closing_milestones.build(milestone: "inspection_cleared", ping_status: "simulated", recorded_at: Time.current)
    assert_not dup.valid?
  end

  test "rejects an unknown milestone or ping_status" do
    o = offer
    assert_not o.closing_milestones.build(milestone: "nope", ping_status: "simulated", recorded_at: Time.current).valid?
    assert_not o.closing_milestones.build(milestone: "funded", ping_status: "weird", recorded_at: Time.current).valid?
  end

  test "Offer tracks order, next milestone, and completion" do
    o = offer
    assert_equal "deal-#{o.id}", o.deal_id
    assert_equal "inspection_cleared", o.next_closing_milestone
    %w[inspection_cleared earnest_deposited title_cleared funded].each do |m|
      o.closing_milestones.create!(milestone: m, ping_status: "simulated", recorded_at: Time.current)
    end
    assert_nil o.reload.next_closing_milestone
    assert o.closing_complete?
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/models/closing_milestone_test.rb`
Expected: FAIL — no `closing_milestones` table / `deal_id`.

- [ ] **Step 3: Migration**

`db/migrate/20260608000001_create_closing_milestones.rb`:

```ruby
class CreateClosingMilestones < ActiveRecord::Migration[8.1]
  def change
    create_table :closing_milestones do |t|
      t.references :offer, null: false, foreign_key: true
      t.string :milestone, null: false
      t.string :counterparty
      t.string :ping_message
      t.string :ping_status, null: false, default: "simulated"
      t.datetime :recorded_at, null: false
      t.timestamps
    end
    add_index :closing_milestones, [:offer_id, :milestone], unique: true
  end
end
```

- [ ] **Step 4: Mirror into `db/schema.rb`**

Bump the version line to `2026_06_08_000001`. Add this `create_table` block (place it right after the `create_table "audit_events"` block — order is cosmetic for SQLite):

```ruby
  create_table "closing_milestones", force: :cascade do |t|
    t.string "counterparty"
    t.datetime "created_at", null: false
    t.string "milestone", null: false
    t.string "ping_message"
    t.string "ping_status", default: "simulated", null: false
    t.integer "offer_id", null: false
    t.datetime "recorded_at", null: false
    t.datetime "updated_at", null: false
    t.index ["offer_id", "milestone"], name: "index_closing_milestones_on_offer_id_and_milestone", unique: true
    t.index ["offer_id"], name: "index_closing_milestones_on_offer_id"
  end
```

And add to the `add_foreign_key` list at the bottom:

```ruby
  add_foreign_key "closing_milestones", "offers"
```

- [ ] **Step 5: Create the model**

`app/models/closing_milestone.rb`:

```ruby
# One met closing milestone on a signed deal (R10). Records which counterparty
# was pinged and whether the ping was emitted by the brain orchestrator
# ("simulated") or queued locally because the brain was unreachable ("pending").
class ClosingMilestone < ApplicationRecord
  MILESTONES = %w[inspection_cleared earnest_deposited title_cleared funded].freeze
  PING_STATUSES = %w[simulated pending].freeze
  COUNTERPARTY_LABEL = { "escrow" => "Escrow officer", "title" => "Title company", "lender" => "Lender" }.freeze

  belongs_to :offer

  validates :milestone, inclusion: { in: MILESTONES }, uniqueness: { scope: :offer_id }
  validates :ping_status, inclusion: { in: PING_STATUSES }

  def counterparty_label = COUNTERPARTY_LABEL[counterparty] || counterparty
end
```

- [ ] **Step 6: Add `Offer` helpers**

In `app/models/offer.rb`, after `has_one :contract, dependent: :destroy` add:

```ruby
  has_many :closing_milestones, dependent: :destroy

  MILESTONE_ORDER = ClosingMilestone::MILESTONES
```

And after `def awaiting_broker_sign?` ... `end`, add:

```ruby
  # Closing pipeline (R10). The deal_id is the stable handle the brain sees.
  def deal_id = "deal-#{id}"

  def recorded_milestones = closing_milestones.pluck(:milestone)

  # The next milestone to record, in canonical order (nil once all are met).
  def next_closing_milestone = (MILESTONE_ORDER - recorded_milestones).first

  def closing_complete? = (MILESTONE_ORDER - recorded_milestones).empty?
```

- [ ] **Step 7: Run the tests — green**

Run: `bin/rails test test/models/closing_milestone_test.rb`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add db/migrate/20260608000001_create_closing_milestones.rb db/schema.rb app/models/closing_milestone.rb app/models/offer.rb test/models/closing_milestone_test.rb
git commit -m "feat: ClosingMilestone model + Offer closing helpers"
```

---

## Task 4: Rails — `ClosingClient` (gRPC)

**Files:**
- Create: `app/services/closing_client.rb`
- Test: `test/services/closing_client_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/services/closing_client_test.rb`:

```ruby
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
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/services/closing_client_test.rb`
Expected: FAIL — `uninitialized constant ClosingClient`.

- [ ] **Step 3: Implement**

`app/services/closing_client.rb` (mirrors `closer_client.rb`):

```ruby
# gRPC client for Closer.RecordMilestone (R10). Asks the brain to route a met
# milestone to its counterparty and emit the (simulated) ping. Mirrors
# CloserClient: same Closer stub, BRAIN_ADDR, and graceful degradation — a
# transport failure returns an error Result so the caller can fall back.
class ClosingClient
  Result = Struct.new(:pinged, :counterparty, :message, :error, keyword_init: true) do
    def ok? = error.nil?
  end

  def initialize(stub: nil, addr: nil)
    @stub = stub
    @addr = addr || ENV.fetch("BRAIN_ADDR", "127.0.0.1:50151")
  end

  def record_milestone(deal_id:, milestone:)
    resp = stub.record_milestone(
      Realestate::V1::RecordMilestoneRequest.new(deal_id: deal_id.to_s, milestone: milestone.to_s)
    )
    Result.new(pinged: resp.pinged, counterparty: resp.counterparty, message: resp.message, error: nil)
  rescue StandardError => e
    Rails.logger.warn("[brain] record_milestone failed: #{e.class}: #{e.message}")
    Result.new(pinged: false, error: "closing_unavailable")
  end

  private

  def stub
    @stub ||= Realestate::V1::Closer::Stub.new(@addr, :this_channel_is_insecure)
  end
end
```

- [ ] **Step 4: Run the tests — green**

Run: `bin/rails test test/services/closing_client_test.rb`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/closing_client.rb test/services/closing_client_test.rb
git commit -m "feat: ClosingClient gRPC client for Closer.RecordMilestone"
```

---

## Task 5: Rails — `ClosingOrchestration` coordinator

**Files:**
- Create: `app/services/closing_orchestration.rb`
- Test: `test/services/closing_orchestration_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/services/closing_orchestration_test.rb`:

```ruby
require "test_helper"

class ClosingOrchestrationTest < ActiveSupport::TestCase
  class OkClient
    def record_milestone(deal_id:, milestone:)
      ClosingClient::Result.new(pinged: true, counterparty: "escrow",
                                message: "Notified escrow: ... for #{deal_id}.", error: nil)
    end
  end

  class DownClient
    def record_milestone(deal_id:, milestone:)
      ClosingClient::Result.new(pinged: false, error: "closing_unavailable")
    end
  end

  def signed_offer
    lead = Lead.create!(side: "buyer", address: "1 A St", contact: "b@x.com", intent: "high")
    Offer.create!(lead: lead, side: "buyer", status: "signed")
  end

  test "records the next milestone, pings via the brain, and audits it" do
    o = signed_offer
    assert_difference -> { AuditEvent.count }, 1 do
      res = ClosingOrchestration.record(offer: o, milestone: "inspection_cleared", client: OkClient.new)
      assert res.recorded?
      assert_equal "escrow", res.counterparty
      assert_equal "simulated", res.ping_status
    end
    cm = o.closing_milestones.find_by(milestone: "inspection_cleared")
    assert_equal "simulated", cm.ping_status
    assert_equal "milestone_recorded", AuditEvent.order(:id).last.kind
  end

  test "is idempotent — re-recording a met milestone is a no-op" do
    o = signed_offer
    ClosingOrchestration.record(offer: o, milestone: "inspection_cleared", client: OkClient.new)
    assert_no_difference -> { ClosingMilestone.count } do
      res = ClosingOrchestration.record(offer: o, milestone: "inspection_cleared", client: OkClient.new)
      assert_not res.recorded?
      assert_equal "already recorded", res.reason
    end
  end

  test "enforces canonical order" do
    o = signed_offer
    res = ClosingOrchestration.record(offer: o, milestone: "funded", client: OkClient.new)
    assert_not res.recorded?
    assert_match(/inspection_cleared first/, res.reason)
    assert_equal 0, o.closing_milestones.count
  end

  test "brain-down still records the milestone, marked pending via local routing" do
    o = signed_offer
    res = ClosingOrchestration.record(offer: o, milestone: "inspection_cleared", client: DownClient.new)
    assert res.recorded?
    assert_equal "escrow", res.counterparty       # from RAILS_ROUTING
    assert_equal "pending", res.ping_status
    assert_equal "pending", o.closing_milestones.first.ping_status
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/services/closing_orchestration_test.rb`
Expected: FAIL — `uninitialized constant ClosingOrchestration`.

- [ ] **Step 3: Implement**

`app/services/closing_orchestration.rb`:

```ruby
# The one place a closing milestone is recorded (R10). Every entry point — the
# broker dashboard button and a completed inspection — goes through here, so
# idempotency, canonical order, the counterparty ping, and the audit entry are
# uniform. Rails owns the state; the brain (ClosingClient) routes + emits the
# (simulated) ping. If the brain is unreachable we still record the milestone,
# routing locally and marking the ping "pending" — honest, never a dead-end.
class ClosingOrchestration
  RAILS_ROUTING = {
    "inspection_cleared" => "escrow", "earnest_deposited" => "escrow",
    "title_cleared" => "title", "funded" => "lender"
  }.freeze
  ACTION = {
    "inspection_cleared" => "inspection cleared — releasing contingency",
    "earnest_deposited" => "earnest-money deposit triggered",
    "title_cleared" => "title cleared — preparing settlement",
    "funded" => "loan funded — ready to disburse"
  }.freeze

  Result = Struct.new(:recorded, :milestone, :counterparty, :ping_message, :ping_status, :reason, keyword_init: true) do
    def recorded? = recorded
  end

  def self.record(offer:, milestone:, client: ClosingClient.new)
    new(offer: offer, milestone: milestone, client: client).record
  end

  def initialize(offer:, milestone:, client:)
    @offer = offer
    @milestone = milestone.to_s
    @client = client
  end

  def record
    unless ClosingMilestone::MILESTONES.include?(@milestone)
      return Result.new(recorded: false, milestone: @milestone, reason: "unknown milestone")
    end
    if @offer.closing_milestones.exists?(milestone: @milestone)
      return Result.new(recorded: false, milestone: @milestone, reason: "already recorded")
    end
    expected = @offer.next_closing_milestone
    if @milestone != expected
      return Result.new(recorded: false, milestone: @milestone, reason: "complete #{expected} first")
    end

    res = @client.record_milestone(deal_id: @offer.deal_id, milestone: @milestone)
    if res.ok?
      counterparty, message, status = res.counterparty, res.message, "simulated"
    else
      counterparty = RAILS_ROUTING[@milestone]
      message = "Notified #{counterparty}: #{ACTION[@milestone]} for #{@offer.deal_id}. (orchestrator unreachable — ping pending)"
      status = "pending"
    end

    @offer.closing_milestones.create!(
      milestone: @milestone, counterparty: counterparty, ping_message: message,
      ping_status: status, recorded_at: Time.current
    )
    AuditEvent.record_rail_trip(
      kind: "milestone_recorded", decision: @milestone, subject: @offer,
      detail: "#{counterparty} pinged (#{status}): #{message}"
    )
    Result.new(recorded: true, milestone: @milestone, counterparty: counterparty,
               ping_message: message, ping_status: status)
  end
end
```

- [ ] **Step 4: Run the tests — green**

Run: `bin/rails test test/services/closing_orchestration_test.rb`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/closing_orchestration.rb test/services/closing_orchestration_test.rb
git commit -m "feat: ClosingOrchestration — records milestones, pings, audits, idempotent + ordered"
```

---

## Task 6: Broker dashboard closing panel + controller + shared tracker

**Files:**
- Create: `app/controllers/broker/closings_controller.rb`
- Modify: `config/routes.rb` (broker offers)
- Modify: `app/controllers/broker/dashboard_controller.rb`
- Create: `app/views/shared/_closing_tracker.html.erb`
- Modify: `app/views/broker/dashboard/show.html.erb`
- Test: `test/controllers/broker/closings_controller_test.rb`

- [ ] **Step 1: Write the failing test**

`services/domain/test/controllers/broker/closings_controller_test.rb`:

```ruby
require "test_helper"

class Broker::ClosingsControllerTest < ActionDispatch::IntegrationTest
  def sign_in_broker
    post session_path, params: { name: "Bro", email: "broker@atlas.example" }
  end

  def signed_offer
    lead = Lead.create!(side: "buyer", address: "9 Deal St", contact: "b@x.com", intent: "high")
    Offer.create!(lead: lead, side: "buyer", status: "signed",
                  property: Property.create!(address: "9 Deal St", state: "listed", list_price: 500_000))
  end

  test "broker records the next milestone and the brain-down path still works" do
    sign_in_broker
    o = signed_offer
    # No brain reachable in test → ClosingClient errors → pending path.
    assert_difference -> { ClosingMilestone.count }, 1 do
      post record_milestone_broker_offer_path(o), params: { milestone: "inspection_cleared" }
    end
    assert_redirected_to broker_dashboard_path
    assert_equal "inspection_cleared", o.closing_milestones.first.milestone
  end

  test "the dashboard shows the closing pipeline tracker for a signed deal" do
    sign_in_broker
    o = signed_offer
    o.closing_milestones.create!(milestone: "inspection_cleared", counterparty: "escrow",
                                 ping_status: "simulated", recorded_at: Time.current)
    get broker_dashboard_path
    assert_response :success
    assert_select "#closing-deals"
    assert_match(/Inspection cleared/i, @response.body)
    assert_match(/Escrow officer/i, @response.body)
  end

  test "out-of-order recording is refused with an alert" do
    sign_in_broker
    o = signed_offer
    post record_milestone_broker_offer_path(o), params: { milestone: "funded" }
    assert_redirected_to broker_dashboard_path
    assert_equal 0, o.closing_milestones.count
  end
end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/controllers/broker/closings_controller_test.rb`
Expected: FAIL — no route `record_milestone_broker_offer_path`.

- [ ] **Step 3: Add the route**

In `config/routes.rb`, replace the broker offers block:

```ruby
    resources :offers, only: [] do
      post :sign, on: :member
    end
```

with:

```ruby
    resources :offers, only: [] do
      member do
        post :sign
        post :record_milestone, to: "broker/closings#create"
      end
    end
```

- [ ] **Step 4: Implement the controller**

`app/controllers/broker/closings_controller.rb`:

```ruby
module Broker
  # Broker records a closing milestone on a signed deal; the orchestrator routes
  # the counterparty ping (R10). Behind require_broker.
  class ClosingsController < BaseController
    def create
      offer = Offer.find(params[:offer_id])
      result = ClosingOrchestration.record(offer: offer, milestone: params[:milestone])
      if result.recorded?
        redirect_to broker_dashboard_path,
          notice: "#{result.milestone.humanize} recorded — #{result.counterparty} notified (#{result.ping_status})."
      else
        redirect_to broker_dashboard_path,
          alert: "Could not record #{params[:milestone]}: #{result.reason}."
      end
    end
  end
end
```

- [ ] **Step 5: Add `@closing_deals` to the dashboard controller**

In `app/controllers/broker/dashboard_controller.rb#show`, add before the final `end`:

```ruby
      # Closing pipeline: signed deals advancing through their milestones (R10).
      @closing_deals = Offer.where(status: "signed").includes(:closing_milestones, :property, :lead).order(:id)
```

- [ ] **Step 6: Create the shared read-only tracker partial**

`app/views/shared/_closing_tracker.html.erb`:

```erb
<%# Read-only closing progress for a deal. Shared by the broker panel and the
    buyer's contract page. Buttons are rendered by the broker view, not here. %>
<% recorded = offer.closing_milestones.index_by(&:milestone) %>
<ol class="mk-closing-steps">
  <% Offer::MILESTONE_ORDER.each do |m| %>
    <% cm = recorded[m] %>
    <li class="closing-step <%= cm ? "is-done" : "is-pending" %>" data-step="<%= m %>">
      <span class="step-name"><%= m.humanize %></span>
      <% if cm %>
        <span class="mk-badge mk-badge--good">✓ <%= cm.counterparty_label %> notified</span>
        <span class="mk-source">
          <%= cm.ping_status == "pending" ? "ping pending (orchestrator unreachable)" : "notified" %>
          · <%= cm.recorded_at.strftime("%b %-d, %Y %-l:%M %p") %>
        </span>
      <% else %>
        <span class="mk-muted">pending</span>
      <% end %>
    </li>
  <% end %>
</ol>
```

- [ ] **Step 7: Add the closing panel to the broker dashboard**

In `app/views/broker/dashboard/show.html.erb`, after the `#time-to-offer` section's closing `</section>`, add:

```erb
<section id="closing-deals" class="mk-card-section">
  <h2>Closing pipeline</h2>
  <% if @closing_deals.any? %>
    <% @closing_deals.each do |offer| %>
      <div class="mk-closing-deal" data-offer="<%= offer.id %>">
        <h3><%= offer.property&.address || "Deal #{offer.id}" %> · <%= offer.deal_id %></h3>
        <%= render "shared/closing_tracker", offer: offer %>
        <% if offer.closing_complete? %>
          <p class="mk-badge mk-badge--good">✅ Closed — funded.</p>
        <% else %>
          <%= button_to "Mark: #{offer.next_closing_milestone.humanize}",
                record_milestone_broker_offer_path(offer),
                params: { milestone: offer.next_closing_milestone }, class: "mk-btn" %>
        <% end %>
      </div>
    <% end %>
  <% else %>
    <p class="mk-muted">No signed deals in closing yet.</p>
  <% end %>
</section>
```

- [ ] **Step 8: Run the tests — green**

Run: `bin/rails test test/controllers/broker/closings_controller_test.rb`
Expected: PASS (3 tests).

- [ ] **Step 9: Commit**

```bash
git add app/controllers/broker/closings_controller.rb config/routes.rb app/controllers/broker/dashboard_controller.rb app/views/shared/_closing_tracker.html.erb app/views/broker/dashboard/show.html.erb test/controllers/broker/closings_controller_test.rb
git commit -m "feat: broker closing pipeline panel + record-milestone action"
```

---

## Task 7: Inspection auto-link (appointment → offer → milestone)

**Files:**
- Create: `db/migrate/20260608000002_add_offer_to_appointments.rb`
- Modify: `db/schema.rb`
- Modify: `app/models/appointment.rb`
- Modify: `app/controllers/broker/appointments_controller.rb`
- Modify: `config/routes.rb` (appointments `complete`)
- Test: `test/controllers/broker/appointments_controller_test.rb`

- [ ] **Step 1: Write the failing test**

Add to `services/domain/test/controllers/broker/appointments_controller_test.rb` (create the file with `require "test_helper"` + `class Broker::AppointmentsControllerTest < ActionDispatch::IntegrationTest` if it does not exist):

```ruby
  def sign_in_broker
    post session_path, params: { name: "Bro", email: "broker@atlas.example" }
  end

  test "completing a linked inspection auto-records inspection_cleared" do
    sign_in_broker
    prop = Property.create!(address: "9 Insp St", state: "listed", list_price: 500_000)
    lead = Lead.create!(side: "buyer", address: "9 Insp St", contact: "b@x.com", intent: "high")
    offer = Offer.create!(lead: lead, side: "buyer", status: "signed", property: prop)
    appt = Appointment.create!(property: prop, kind: "inspection", status: "confirmed", offer: offer,
                               starts_at: 1.day.from_now, ends_at: 1.day.from_now + 30.minutes,
                               broker_email: "broker@atlas.example")
    assert_difference -> { ClosingMilestone.count }, 1 do
      post complete_broker_appointment_path(appt)
    end
    assert_equal "completed", appt.reload.status
    assert_equal "inspection_cleared", offer.closing_milestones.first.milestone
  end

  test "completing a tour records no milestone" do
    sign_in_broker
    prop = Property.create!(address: "9 Tour St", state: "listed", list_price: 500_000)
    appt = Appointment.create!(property: prop, kind: "tour", status: "confirmed",
                               starts_at: 1.day.from_now, ends_at: 1.day.from_now + 30.minutes)
    assert_no_difference -> { ClosingMilestone.count } do
      post complete_broker_appointment_path(appt)
    end
  end
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/controllers/broker/appointments_controller_test.rb`
Expected: FAIL — no `complete_broker_appointment_path` / no `offer` on Appointment.

- [ ] **Step 3: Migration + schema**

`db/migrate/20260608000002_add_offer_to_appointments.rb`:

```ruby
class AddOfferToAppointments < ActiveRecord::Migration[8.1]
  def change
    add_reference :appointments, :offer, null: true, foreign_key: true
  end
end
```

In `db/schema.rb`: bump the version to `2026_06_08_000002`. In the `create_table "appointments"` block add (keep alphabetical-ish):

```ruby
    t.integer "offer_id"
```

and within that block's indexes add:

```ruby
    t.index ["offer_id"], name: "index_appointments_on_offer_id"
```

and add to the foreign-key list:

```ruby
  add_foreign_key "appointments", "offers"
```

- [ ] **Step 4: Appointment model — association + resolver**

In `app/models/appointment.rb`, after `belongs_to :lead, optional: true` add:

```ruby
  belongs_to :offer, optional: true
```

And add a public method (after the `overlaps?` method):

```ruby
  # The signed deal this (inspection) appointment belongs to: an explicit offer,
  # else the lone signed offer on this property — disambiguated by the requester's
  # email when there is more than one. nil when nothing resolves.
  def resolve_offer
    return offer if offer

    scope = Offer.where(property_id: property_id, status: "signed")
    by_email = scope.joins(:lead).where(leads: { contact: requester_email })
    by_email.first || (scope.count == 1 ? scope.first : nil)
  end
```

- [ ] **Step 5: Controller `complete` action**

In `app/controllers/broker/appointments_controller.rb`, add after `decline`:

```ruby
    def complete
      appt = Appointment.find(params[:id])
      appt.update!(status: "completed")
      AuditEvent.record_rail_trip(kind: "showing_completed", decision: "completed", subject: appt,
        detail: "#{appt.kind} for #{appt.property.address}")

      # A completed inspection on a resolvable deal clears the first closing
      # milestone (R10) — same coordinator as the broker button.
      if appt.kind == "inspection" && (deal = appt.resolve_offer)
        ClosingOrchestration.record(offer: deal, milestone: "inspection_cleared")
      end

      redirect_to broker_dashboard_path, notice: "Appointment marked completed."
    end
```

- [ ] **Step 6: Route**

In `config/routes.rb`, extend the broker appointments member block:

```ruby
    resources :appointments, only: [] do
      member do
        post :confirm
        post :decline
        post :complete
      end
    end
```

- [ ] **Step 7: Run the tests — green**

Run: `bin/rails test test/controllers/broker/appointments_controller_test.rb`
Expected: PASS (the two new tests + any pre-existing).

- [ ] **Step 8: Commit**

```bash
git add db/migrate/20260608000002_add_offer_to_appointments.rb db/schema.rb app/models/appointment.rb app/controllers/broker/appointments_controller.rb config/routes.rb test/controllers/broker/appointments_controller_test.rb
git commit -m "feat: completing a linked inspection auto-clears the inspection milestone"
```

---

## Task 8: Buyer-visible read-only closing tracker

**Files:**
- Modify: `app/views/consumer/contracts/show.html.erb`
- Test: `test/controllers/consumer/contracts_controller_test.rb`

- [ ] **Step 1: Write the failing test**

Add to `services/domain/test/controllers/consumer/contracts_controller_test.rb` (create with the standard header if absent):

```ruby
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
```

- [ ] **Step 2: Run it — fail**

Run: `bin/rails test test/controllers/consumer/contracts_controller_test.rb -n "/read-only closing tracker/"`
Expected: FAIL — no `#closing-tracker`.

- [ ] **Step 3: Add the tracker section to the contract page**

Append to `app/views/consumer/contracts/show.html.erb`:

```erb
<section class="mk-card-section" id="closing-tracker">
  <h2>Closing progress</h2>
  <%= render "shared/closing_tracker", offer: @contract.offer %>
  <p class="mk-source">Escrow / title / lender notifications are simulated in this demo — a licensed broker drives each step.</p>
</section>
```

- [ ] **Step 4: Run the test — green**

Run: `bin/rails test test/controllers/consumer/contracts_controller_test.rb -n "/read-only closing tracker/"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/views/consumer/contracts/show.html.erb test/controllers/consumer/contracts_controller_test.rb
git commit -m "feat: buyer-visible read-only closing tracker on the contract page"
```

---

## Task 9: Docs + full suites + final commit

**Files:**
- Modify: `services/domain/README.md`, root `README.md`, spec status line.

- [ ] **Step 1: Run the FULL brain suite**

Run: `cd services/brain && PYTHONPATH=src python3 -m pytest -q 2>&1 | tail -5`
Expected: all pass (prior ~238 + 3 new), 0 failures.

- [ ] **Step 2: Run the FULL Rails suite**

Run: `cd services/domain && eval "$(rbenv init - zsh)" && bin/rails test 2>&1 | tail -5`
Expected: all pass (prior 289 + new), 0 failures/errors. Record the new count.

- [ ] **Step 3: Verify Go builds**

Run: `cd "/Users/rikki/Desktop/AI Real Estate Agent" && go build ./... 2>&1 | tail -3`
Expected: clean.

- [ ] **Step 4: Update `services/domain/README.md`** — add a subsection:

```markdown
## Closing orchestration (R10)

After a broker signs an offer, the deal advances through four milestones
(inspection cleared → earnest deposited → title cleared → funded) on the broker
dashboard's **Closing pipeline**. Each recorded milestone calls the brain's
`Closer.RecordMilestone` RPC, which routes the (simulated) counterparty ping —
escrow / title / lender — and Rails persists it on `ClosingMilestone` and writes
an append-only `AuditEvent`. Rails owns idempotency + canonical order; if the
brain is unreachable the milestone is still recorded, routed locally, and marked
`pending` (honest). Completing a linked **inspection** appointment auto-clears the
first milestone. The buyer sees a **read-only** closing tracker on their contract;
real escrow/title/lender integrations remain a documented seam.
```

- [ ] **Step 5: Update root `README.md`** — set capability #9 (Closing Orchestration) to live/real and bump the Rails test count to the new total from Step 2.

- [ ] **Step 6: Flip the spec status** to `Status: Implemented` in the design doc header.

- [ ] **Step 7: Final commit**

```bash
git add services/domain/README.md README.md docs/superpowers/specs/2026-06-08-closing-orchestration-design.md
git commit -m "docs: closing orchestration wired (R10)"
```

---

## Self-Review

**Spec coverage:**
- A. `Closer.RecordMilestone` RPC + servicer → Tasks 1, 2. ✓
- B. `ClosingMilestone` + `Offer` helpers (deal = signed offer) → Task 3. ✓
- C. `ClosingClient` + `ClosingOrchestration` (idempotent, ordered, audited, brain-down fallback) → Tasks 4, 5. ✓
- D. Broker dashboard panel + button + controller → Task 6. ✓
- E. Inspection auto-link → Task 7. ✓
- F. Buyer read-only tracker → Task 8. ✓
- G. Invariants/tests → each task is TDD; brain RPC valid/invalid, idempotency, order, fallback, broker button, inspection auto-record, buyer read-only all covered. Docs → Task 9. ✓

**Placeholder scan:** none — all code is concrete.

**Type/name consistency:** `RecordMilestoneRequest/Response` (proto) ↔ `pb.RecordMilestoneResponse` (brain) ↔ `Realestate::V1::RecordMilestoneRequest` (Ruby). `ClosingClient::Result(pinged,counterparty,message,error)` ↔ consumed in `ClosingOrchestration`. `ClosingOrchestration::Result(recorded,milestone,counterparty,ping_message,ping_status,reason)` ↔ used in `Broker::ClosingsController`. `Offer#deal_id/#next_closing_milestone/#closing_complete?/MILESTONE_ORDER`, `ClosingMilestone::MILESTONES/#counterparty_label`, `record_milestone_broker_offer_path`, `complete_broker_appointment_path` — all consistent across tasks. `RAILS_ROUTING` matches the brain's `MILESTONE_COUNTERPARTY`. Migration versions `…000001` (closing_milestones) then `…000002` (appointments offer) → schema version `2026_06_08_000002`.

**Notes for the implementer:**
- Brain tests need the regenerated proto (Task 1) before Task 2 passes.
- The broker controller test (Task 6) deliberately exercises the **brain-down** path (no brain in the Rails test env → `ClosingClient` errors → `pending`), so it asserts the milestone is recorded without asserting `simulated`.
- If `python3` lacks `grpc`, use `/opt/anaconda3/bin/python3` for the brain pytest/regeneration.
