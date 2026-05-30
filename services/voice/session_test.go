package main

import "testing"

// Thread/context continuity: the same session id returns a growing thread
// across multiple turns (R6).
func TestSessionThreadPersistsAcrossTurns(t *testing.T) {
	m := NewManager()
	sess := m.Start()

	if len(sess.Thread) != 0 {
		t.Fatalf("new session should have empty thread, got %d turns", len(sess.Thread))
	}

	if _, ok := m.AppendTurn(sess.ID, RoleSeller, "Hi, I want to sell.", nil); !ok {
		t.Fatal("AppendTurn returned ok=false for an existing session")
	}
	got, ok := m.AppendTurn(sess.ID, RoleAgent, "Happy to help — what's the address?", nil)
	if !ok {
		t.Fatal("second AppendTurn returned ok=false")
	}

	if len(got.Thread) != 2 {
		t.Fatalf("thread should have 2 turns after 2 appends, got %d", len(got.Thread))
	}
	if got.Thread[0].Role != RoleSeller || got.Thread[1].Role != RoleAgent {
		t.Fatalf("turns out of order: %+v", got.Thread)
	}

	// Get returns the same persisted thread.
	fetched, ok := m.Get(sess.ID)
	if !ok || len(fetched.Thread) != 2 {
		t.Fatalf("Get did not return the persisted 2-turn thread: ok=%v turns=%d", ok, len(fetched.Thread))
	}
}

// Neutral fields collected across turns accumulate on the session.
func TestSessionFieldsAccumulate(t *testing.T) {
	m := NewManager()
	sess := m.Start()

	m.AppendTurn(sess.ID, RoleSeller, "123 Main St", map[string]string{"address": "123 Main St"})
	got, _ := m.AppendTurn(sess.ID, RoleSeller, "within 30 days", map[string]string{
		"timeline": "30 days",
		"blank":    "", // empty value must not be stored
	})

	if got.Fields["address"] != "123 Main St" {
		t.Fatalf("address not retained across turns: %q", got.Fields["address"])
	}
	if got.Fields["timeline"] != "30 days" {
		t.Fatalf("timeline not stored: %q", got.Fields["timeline"])
	}
	if _, present := got.Fields["blank"]; present {
		t.Fatal("empty-valued field should not be stored")
	}
}

// Snapshots are deep copies: mutating a returned snapshot must not leak back
// into the manager's stored session.
func TestSnapshotIsolation(t *testing.T) {
	m := NewManager()
	sess := m.Start()
	got, _ := m.AppendTurn(sess.ID, RoleSeller, "hi", map[string]string{"address": "x"})

	got.Fields["address"] = "TAMPERED"
	got.Thread = append(got.Thread, Turn{Role: RoleAgent, Text: "leak"})

	fresh, _ := m.Get(sess.ID)
	if fresh.Fields["address"] != "x" {
		t.Fatalf("snapshot mutation leaked into stored session: %q", fresh.Fields["address"])
	}
	if len(fresh.Thread) != 1 {
		t.Fatalf("snapshot thread mutation leaked: %d turns", len(fresh.Thread))
	}
}

// Unknown session id is reported, not auto-created.
func TestAppendUnknownSession(t *testing.T) {
	m := NewManager()
	if _, ok := m.AppendTurn("nope", RoleSeller, "hi", nil); ok {
		t.Fatal("AppendTurn should return ok=false for unknown session id")
	}
}
