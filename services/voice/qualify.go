// Package main — Voice transport (U11).
//
// qualify.go is the intent-triage half of seller intake (R5): given the neutral
// fields a session has collected, it decides high-intent seller vs low-intent
// browser. The triage is computed ONLY from neutral, transaction-relevant
// signals — an address plus a stated timeline or motivation to sell. It NEVER
// reads protected-class or proxy signals: those keys are not in the neutral set
// and are structurally excluded, which is the equal-service guarantee on the
// Voice side (mirrors brain.lawyer.fair_housing.EQUAL_SERVICE_GUARANTEE).
package main

import "strings"

// Intent is the triaged seller-intent label.
type Intent string

const (
	// IntentHighSeller is a qualified, transaction-ready seller.
	IntentHighSeller Intent = "high_intent_seller"
	// IntentLowBrowser is a vague / low-intent inquiry.
	IntentLowBrowser Intent = "low_intent_browser"
)

// NeutralSignals is the fixed allow-list of neutral, transaction-relevant field
// keys the qualifier is permitted to read. Anything not here (an inferred
// attribute or a proxy) is never consulted — qualification cannot branch on it.
var NeutralSignals = []string{
	"address",
	"timeline",
	"motivation",
}

// Qualification is the structured triage result handed back to the caller and,
// for a qualified seller, forwarded to the orchestrator's seller_intake seam.
type Qualification struct {
	Intent      Intent   `json:"intent"`
	HighIntent  bool     `json:"high_intent"`
	HasAddress  bool     `json:"has_address"`
	Reason      string   `json:"reason"`
	SignalsUsed []string `json:"signals_used"`
}

// nonEmpty reports whether a neutral field is present and non-blank.
func nonEmpty(fields map[string]string, key string) bool {
	return strings.TrimSpace(fields[key]) != ""
}

// Qualify triages seller intent from collected neutral fields only.
//
// High-intent requires BOTH:
//   - an address (the subject property), AND
//   - at least one stated transaction signal: a timeline or a motivation to sell.
//
// Anything short of that stays low-intent — it does NOT invent missing data.
// The qualifier reads only NeutralSignals keys, so non-neutral fields present on
// the session can never change the outcome (equal service).
func Qualify(fields map[string]string) Qualification {
	hasAddress := nonEmpty(fields, "address")
	hasTimeline := nonEmpty(fields, "timeline")
	hasMotivation := nonEmpty(fields, "motivation")

	used := make([]string, 0, len(NeutralSignals))
	if hasAddress {
		used = append(used, "address")
	}
	if hasTimeline {
		used = append(used, "timeline")
	}
	if hasMotivation {
		used = append(used, "motivation")
	}

	if hasAddress && (hasTimeline || hasMotivation) {
		return Qualification{
			Intent:      IntentHighSeller,
			HighIntent:  true,
			HasAddress:  true,
			Reason:      "address plus a stated timeline/motivation to sell",
			SignalsUsed: used,
		}
	}

	return Qualification{
		Intent:      IntentLowBrowser,
		HighIntent:  false,
		HasAddress:  hasAddress,
		Reason:      "insufficient neutral signals: need address and a timeline/motivation to sell",
		SignalsUsed: used,
	}
}

// NeutralFields returns a copy of fields restricted to the neutral allow-list.
// This is the seam that hands the orchestrator's seller_intake ONLY neutral,
// transaction-relevant data — inferred attributes never cross the boundary.
func NeutralFields(fields map[string]string) map[string]string {
	out := make(map[string]string, len(NeutralSignals))
	for _, k := range NeutralSignals {
		if v := strings.TrimSpace(fields[k]); v != "" {
			out[k] = v
		}
	}
	return out
}
