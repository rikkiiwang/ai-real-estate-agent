// disclosure.go — AI-disclosure rail for the Voice transport (U17, R10).
//
// Outreach compliance (SB 140 / federal TCPA, see the plan's Risks): when the
// agent contacts a consumer on an automated voice channel it MUST disclose that
// the voice is AI-generated within the FIRST 30 SECONDS — before any
// substantive conversation. Text channels (chat/SMS) get a lighter, voluntary
// disclosure line; the disclosure is offered but not legally gated on a timer.
//
// This file is deliberately stdlib-only and side-effect-free: it produces the
// disclosure text and a Tracker that records WHEN the disclosure was issued so
// the session/transport can prove (and enforce) that voice disclosed AI before
// the first substantive turn. The consent gate that decides whether a consumer
// may be contacted at all lives in the Rails domain (Consent model); this rail
// covers only the AI-disclosure half of the requirement.
package main

import "time"

// Channel is the outreach medium a session runs on. Disclosure rules differ by
// channel: voice is hard-gated on a 30-second timer, text channels are
// voluntary.
type Channel string

const (
	// ChannelVoice is an automated voice call. AI disclosure is MANDATORY and
	// must land within VoiceDisclosureDeadline of the call connecting, before any
	// substantive turn.
	ChannelVoice Channel = "voice"
	// ChannelChat is a web/app chat thread. AI disclosure is voluntary.
	ChannelChat Channel = "chat"
	// ChannelSMS is a text-message thread. AI disclosure is voluntary.
	ChannelSMS Channel = "sms"
)

// VoiceDisclosureDeadline is the hard window for the mandatory voice AI
// disclosure: it must be issued within the first 30 seconds of the call.
const VoiceDisclosureDeadline = 30 * time.Second

// voiceDisclosureText is the AI-generated-voice disclosure spoken at the top of
// every automated voice call. Plain, non-deceptive, and channel-appropriate.
const voiceDisclosureText = "Before we begin: this call uses an AI-generated " +
	"voice from an automated real-estate assistant, not a live person. You can " +
	"ask to speak with a human at any time."

// textDisclosureText is the lighter, voluntary disclosure line for chat/SMS.
const textDisclosureText = "Heads up: you're chatting with an automated, " +
	"AI-powered real-estate assistant. Ask for a human anytime."

// DisclosureText returns the AI-disclosure copy for a channel. Voice gets the
// mandatory spoken disclosure; chat/SMS get the voluntary line. An unknown
// channel falls back to the voluntary text (fail-safe toward MORE disclosure).
func DisclosureText(ch Channel) string {
	if ch == ChannelVoice {
		return voiceDisclosureText
	}
	return textDisclosureText
}

// MandatoryDisclosure reports whether the channel hard-requires an AI
// disclosure before substantive conversation. Only voice is gated; text
// channels are voluntary.
func MandatoryDisclosure(ch Channel) bool {
	return ch == ChannelVoice
}

// DisclosureTracker records whether (and when) the AI disclosure was issued on a
// session, relative to when the channel opened, so the transport can prove the
// voice disclosure landed inside VoiceDisclosureDeadline and BEFORE any
// substantive turn. It is not concurrency-safe by itself; callers serialize it
// through the session it belongs to.
type DisclosureTracker struct {
	channel  Channel
	openedAt time.Time
	issuedAt *time.Time // nil until the disclosure is issued
	now      func() time.Time
}

// NewDisclosureTracker starts tracking disclosure for a channel that opened at
// openedAt. now is the clock used to stamp the disclosure (injectable for
// tests); nil defaults to time.Now.
func NewDisclosureTracker(ch Channel, openedAt time.Time, now func() time.Time) *DisclosureTracker {
	if now == nil {
		now = time.Now
	}
	return &DisclosureTracker{channel: ch, openedAt: openedAt, now: now}
}

// Disclose records that the AI disclosure has been issued, stamping the current
// time. Idempotent: repeat calls keep the FIRST (earliest) issuance, since
// that's the moment that matters for the 30-second window. Returns the
// disclosure text that should be delivered on the channel.
func (t *DisclosureTracker) Disclose() string {
	if t.issuedAt == nil {
		at := t.now()
		t.issuedAt = &at
	}
	return DisclosureText(t.channel)
}

// Disclosed reports whether the AI disclosure has been issued at all.
func (t *DisclosureTracker) Disclosed() bool {
	return t.issuedAt != nil
}

// CanProceed reports whether a SUBSTANTIVE turn is allowed on this channel right
// now. On voice it returns false until the disclosure has been issued: no
// substantive conversation may precede the AI disclosure. On chat/SMS it is
// always true (disclosure is voluntary, not blocking).
func (t *DisclosureTracker) CanProceed() bool {
	if !MandatoryDisclosure(t.channel) {
		return true
	}
	return t.Disclosed()
}

// Compliant reports whether the channel's AI-disclosure obligation is satisfied.
// Voice requires the disclosure to have been issued within
// VoiceDisclosureDeadline of the channel opening; chat/SMS are always compliant
// (voluntary). A voice disclosure that never issued, or issued late, is
// non-compliant.
func (t *DisclosureTracker) Compliant() bool {
	if !MandatoryDisclosure(t.channel) {
		return true
	}
	if t.issuedAt == nil {
		return false
	}
	return !t.issuedAt.After(t.openedAt.Add(VoiceDisclosureDeadline))
}
