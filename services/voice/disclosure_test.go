package main

import (
	"strings"
	"testing"
	"time"
)

// Voice MUST disclose AI before any substantive turn: until the disclosure is
// issued, the tracker blocks proceeding (R10).
func TestVoiceBlocksSubstantiveTurnUntilDisclosed(t *testing.T) {
	opened := time.Date(2026, 5, 29, 12, 0, 0, 0, time.UTC)
	clock := opened
	tr := NewDisclosureTracker(ChannelVoice, opened, func() time.Time { return clock })

	if tr.CanProceed() {
		t.Fatal("voice should NOT allow a substantive turn before AI disclosure")
	}
	if tr.Disclosed() {
		t.Fatal("disclosure should not be marked issued before Disclose()")
	}

	text := tr.Disclose()
	if !strings.Contains(strings.ToLower(text), "ai-generated voice") {
		t.Fatalf("voice disclosure must state the voice is AI-generated, got %q", text)
	}
	if !tr.CanProceed() {
		t.Fatal("voice should allow substantive turns once AI disclosure is issued")
	}
}

// Voice disclosure inside the first 30 seconds is compliant; after it is not.
func TestVoiceDisclosureWithinThirtySeconds(t *testing.T) {
	opened := time.Date(2026, 5, 29, 12, 0, 0, 0, time.UTC)

	// Issued at 25s — within the window.
	clock := opened.Add(25 * time.Second)
	onTime := NewDisclosureTracker(ChannelVoice, opened, func() time.Time { return clock })
	onTime.Disclose()
	if !onTime.Compliant() {
		t.Fatal("disclosure at 25s should be compliant (within 30s)")
	}

	// Issued at exactly 30s — still within the window (boundary inclusive).
	clock2 := opened.Add(VoiceDisclosureDeadline)
	boundary := NewDisclosureTracker(ChannelVoice, opened, func() time.Time { return clock2 })
	boundary.Disclose()
	if !boundary.Compliant() {
		t.Fatal("disclosure at exactly 30s should be compliant")
	}

	// Issued at 31s — too late.
	clock3 := opened.Add(31 * time.Second)
	late := NewDisclosureTracker(ChannelVoice, opened, func() time.Time { return clock3 })
	late.Disclose()
	if late.Compliant() {
		t.Fatal("disclosure at 31s should be NON-compliant (past 30s)")
	}
}

// A voice call that never discloses AI is non-compliant.
func TestVoiceNeverDisclosedIsNonCompliant(t *testing.T) {
	opened := time.Now()
	tr := NewDisclosureTracker(ChannelVoice, opened, nil)
	if tr.Compliant() {
		t.Fatal("voice with no disclosure issued must be non-compliant")
	}
	if tr.CanProceed() {
		t.Fatal("voice with no disclosure must block substantive turns")
	}
}

// Chat/SMS get a voluntary disclosure line: it never blocks and is always
// compliant, but the text is still available and present.
func TestTextChannelsVoluntaryDisclosure(t *testing.T) {
	for _, ch := range []Channel{ChannelChat, ChannelSMS} {
		tr := NewDisclosureTracker(ch, time.Now(), nil)
		if MandatoryDisclosure(ch) {
			t.Fatalf("%s disclosure should be voluntary, not mandatory", ch)
		}
		if !tr.CanProceed() {
			t.Fatalf("%s should allow conversation without a forced disclosure", ch)
		}
		if !tr.Compliant() {
			t.Fatalf("%s should be compliant without a timed disclosure", ch)
		}
		text := tr.Disclose()
		if !strings.Contains(strings.ToLower(text), "automated") {
			t.Fatalf("%s voluntary disclosure should flag the automated assistant, got %q", ch, text)
		}
	}
}

// Disclose is idempotent and keeps the first (earliest) issuance time, so a
// re-disclosure cannot retroactively make a late call look on-time.
func TestDiscloseKeepsEarliestIssuance(t *testing.T) {
	opened := time.Date(2026, 5, 29, 12, 0, 0, 0, time.UTC)
	clock := opened.Add(10 * time.Second)
	tr := NewDisclosureTracker(ChannelVoice, opened, func() time.Time { return clock })
	tr.Disclose() // issued at 10s

	clock = opened.Add(45 * time.Second) // a later re-disclosure
	tr.Disclose()

	if !tr.Compliant() {
		t.Fatal("re-disclosing later must not erase the original on-time issuance")
	}
}
