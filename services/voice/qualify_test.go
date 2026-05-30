package main

import "testing"

// A seller giving address + timeline qualifies high-intent (R5 happy path).
func TestSellerWithAddressAndTimelineIsHighIntent(t *testing.T) {
	q := Qualify(map[string]string{
		"address":  "123 Main St Austin TX",
		"timeline": "30 days",
	})
	if !q.HighIntent || q.Intent != IntentHighSeller {
		t.Fatalf("address+timeline should be high-intent, got %+v", q)
	}
}

// Address + motivation also qualifies high-intent.
func TestSellerWithAddressAndMotivationIsHighIntent(t *testing.T) {
	q := Qualify(map[string]string{
		"address":    "123 Main St",
		"motivation": "relocating for work",
	})
	if !q.HighIntent || q.Intent != IntentHighSeller {
		t.Fatalf("address+motivation should be high-intent, got %+v", q)
	}
}

// A vague inquiry stays low-intent without inventing missing data (R5 edge).
func TestVagueInquiryStaysLowIntent(t *testing.T) {
	// Only a curiosity message, no neutral transaction signals.
	q := Qualify(map[string]string{})
	if q.HighIntent || q.Intent != IntentLowBrowser {
		t.Fatalf("empty inquiry should stay low-intent, got %+v", q)
	}

	// Address alone (no timeline/motivation) is not enough — don't invent intent.
	q2 := Qualify(map[string]string{"address": "123 Main St"})
	if q2.HighIntent {
		t.Fatalf("address-only should remain low-intent, got %+v", q2)
	}
	if !q2.HasAddress {
		t.Fatal("address-only should still report HasAddress=true")
	}
}

// Qualification ignores / does not branch on non-neutral fields. Adding
// protected-class or proxy fields must not change the outcome (equal service).
func TestQualifyIgnoresNonNeutralFields(t *testing.T) {
	neutral := map[string]string{"address": "123 Main St", "timeline": "30 days"}
	base := Qualify(neutral)

	withProtected := Qualify(map[string]string{
		"address":       "123 Main St",
		"timeline":      "30 days",
		"race":          "white",
		"family_status": "has children",
		"good_schools":  "true",
		"age":           "senior",
	})
	if withProtected.Intent != base.Intent || withProtected.HighIntent != base.HighIntent {
		t.Fatalf("non-neutral fields changed qualification: base=%+v with=%+v", base, withProtected)
	}

	// A low-intent case must NOT be lifted high by a non-neutral field.
	lowWithProtected := Qualify(map[string]string{
		"address": "123 Main St",
		"race":    "white", // not a transaction signal
	})
	if lowWithProtected.HighIntent {
		t.Fatalf("non-neutral field must not qualify intent, got %+v", lowWithProtected)
	}

	// SignalsUsed only ever names neutral keys.
	for _, k := range withProtected.SignalsUsed {
		if k != "address" && k != "timeline" && k != "motivation" {
			t.Fatalf("SignalsUsed leaked a non-neutral key: %q", k)
		}
	}
}

// NeutralFields strips everything outside the neutral allow-list before the
// orchestrator seam sees it.
func TestNeutralFieldsStripsNonNeutral(t *testing.T) {
	out := NeutralFields(map[string]string{
		"address":  "123 Main St",
		"timeline": "30 days",
		"race":     "white",
		"blank":    "",
	})
	if len(out) != 2 || out["address"] != "123 Main St" || out["timeline"] != "30 days" {
		t.Fatalf("NeutralFields did not restrict to the allow-list: %+v", out)
	}
}
