package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func newTestServer() http.Handler {
	return newMux(&server{manager: NewManager()})
}

// /health still works alongside the conversation API.
func TestHealthEndpoint(t *testing.T) {
	srv := httptest.NewServer(newTestServer())
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/health")
	if err != nil {
		t.Fatalf("GET /health: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("/health status = %d", resp.StatusCode)
	}
	var body map[string]string
	json.NewDecoder(resp.Body).Decode(&body)
	if body["service"] != "voice" || body["status"] != "ok" {
		t.Fatalf("unexpected health body: %+v", body)
	}
}

// End-to-end conversation: start a session, then add turns whose thread persists
// and whose neutral signals qualify the seller high-intent.
func TestConversationAPIThreadAndQualification(t *testing.T) {
	srv := httptest.NewServer(newTestServer())
	defer srv.Close()

	// Start a session.
	startResp, err := http.Post(srv.URL+"/session", "application/json", nil)
	if err != nil {
		t.Fatalf("POST /session: %v", err)
	}
	defer startResp.Body.Close()
	if startResp.StatusCode != http.StatusCreated {
		t.Fatalf("POST /session status = %d", startResp.StatusCode)
	}
	var started messageResponse
	json.NewDecoder(startResp.Body).Decode(&started)
	id := started.Session.ID
	if id == "" {
		t.Fatal("start did not return a session id")
	}
	if started.Qualification.HighIntent {
		t.Fatal("fresh session should not be high-intent")
	}

	// Turn 1: address only -> still low-intent (no invented data).
	r1 := postMessage(t, srv.URL, id, messageRequest{
		Text:   "I'd like to sell 123 Main St.",
		Fields: map[string]string{"address": "123 Main St Austin TX"},
	})
	if r1.Qualification.HighIntent {
		t.Fatalf("address-only turn should stay low-intent, got %+v", r1.Qualification)
	}
	if len(r1.Session.Thread) != 1 {
		t.Fatalf("expected 1 turn, got %d", len(r1.Session.Thread))
	}

	// Turn 2: add timeline -> high-intent, thread now 2 turns (continuity).
	r2 := postMessage(t, srv.URL, id, messageRequest{
		Text:   "Hoping to close within 30 days.",
		Fields: map[string]string{"timeline": "30 days"},
	})
	if !r2.Qualification.HighIntent || r2.Qualification.Intent != IntentHighSeller {
		t.Fatalf("address+timeline should qualify high-intent, got %+v", r2.Qualification)
	}
	if len(r2.Session.Thread) != 2 {
		t.Fatalf("thread continuity broken: expected 2 turns, got %d", len(r2.Session.Thread))
	}
	if r2.Session.Fields["address"] != "123 Main St Austin TX" {
		t.Fatalf("address from turn 1 not retained: %q", r2.Session.Fields["address"])
	}
}

// Posting to an unknown session returns 404 (no auto-create).
func TestMessageToUnknownSession(t *testing.T) {
	srv := httptest.NewServer(newTestServer())
	defer srv.Close()

	body, _ := json.Marshal(messageRequest{Text: "hi"})
	resp, err := http.Post(srv.URL+"/session/does-not-exist/message", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("POST message: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusNotFound {
		t.Fatalf("expected 404 for unknown session, got %d", resp.StatusCode)
	}
}

func TestParseMessagePath(t *testing.T) {
	cases := map[string]struct {
		wantID string
		wantOK bool
	}{
		"/session/abc/message":     {"abc", true},
		"/session//message":        {"", false},
		"/session/a/b/message":     {"", false},
		"/session/abc":             {"", false},
		"/health":                  {"", false},
		"/session/abc/message/foo": {"", false},
	}
	for path, want := range cases {
		id, ok := parseMessagePath(path)
		if id != want.wantID || ok != want.wantOK {
			t.Errorf("parseMessagePath(%q) = (%q, %v), want (%q, %v)", path, id, ok, want.wantID, want.wantOK)
		}
	}
}

func postMessage(t *testing.T, base, id string, req messageRequest) messageResponse {
	t.Helper()
	body, _ := json.Marshal(req)
	url := base + "/session/" + id + "/message"
	resp, err := http.Post(url, "application/json", strings.NewReader(string(body)))
	if err != nil {
		t.Fatalf("POST %s: %v", url, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("POST %s status = %d", url, resp.StatusCode)
	}
	var out messageResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return out
}
