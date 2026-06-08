// Command voice is the single-channel conversation transport (U11). It holds
// channel sessions and thread continuity (session.go), triages seller intent
// from neutral signals only (qualify.go), and exposes a minimal single-channel
// conversation API over HTTP. The API is architected so additional channels
// attach to the same Session/Qualification contract.
//
// Routes:
//
//	GET  /health                 — shared health check (internal/health).
//	POST /session                — start a new conversation, returns the session.
//	POST /session/{id}/message   — add a seller turn (+ optional neutral fields),
//	                               returns the updated thread + qualification.
//	GET  /disclosure?channel=    — AI-disclosure copy + whether it's mandatory
//	                               for the channel (voice|chat|sms); see
//	                               disclosure.go (U17, R10).
package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"

	"github.com/airealestate/realestate/internal/health"
)

// server wires the HTTP conversation API over an in-memory session Manager. When
// a relay is configured (DOMAIN_URL set), each turn also joins the Rails shared
// cross-channel thread (R4).
type server struct {
	manager *Manager
	relay   ThreadRelay
}

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

// messageRequest is the body of POST /session/{id}/message.
type messageRequest struct {
	Text   string            `json:"text"`
	Fields map[string]string `json:"fields"`
}

// messageResponse is returned from both session endpoints: the updated session
// thread plus the current intent qualification computed from neutral signals.
type messageResponse struct {
	Session       Session       `json:"session"`
	Qualification Qualification `json:"qualification"`
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// handleSession starts a new conversation. POST /session.
func (s *server) handleSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}
	sess := s.manager.Start()
	writeJSON(w, http.StatusCreated, messageResponse{
		Session:       sess,
		Qualification: Qualify(sess.Fields),
	})
}

// handleMessage adds a seller turn to an existing session and returns the
// updated thread + qualification. POST /session/{id}/message.
func (s *server) handleMessage(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}
	id, ok := parseMessagePath(r.URL.Path)
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
		return
	}

	var req messageRequest
	if r.Body != nil {
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil && err.Error() != "EOF" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON body"})
			return
		}
	}

	sess, found := s.manager.AppendTurn(id, RoleSeller, req.Text, req.Fields)
	if !found {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "session not found"})
		return
	}

	// Join the Rails shared thread (if configured): append the agent's reply and
	// return the refreshed session so the thread includes both turns.
	if _, ok := s.relayReply(id, req.Text); ok {
		if refreshed, ok := s.manager.Get(id); ok {
			sess = refreshed
		}
	}

	writeJSON(w, http.StatusOK, messageResponse{
		Session:       sess,
		Qualification: Qualify(sess.Fields),
	})
}

// parseMessagePath extracts {id} from "/session/{id}/message". Done by hand so
// the transport stays stdlib-only and version-agnostic.
func parseMessagePath(path string) (string, bool) {
	const prefix = "/session/"
	const suffix = "/message"
	if !strings.HasPrefix(path, prefix) || !strings.HasSuffix(path, suffix) {
		return "", false
	}
	id := strings.TrimSuffix(strings.TrimPrefix(path, prefix), suffix)
	if id == "" || strings.Contains(id, "/") {
		return "", false
	}
	return id, true
}

// disclosureResponse is returned from GET /disclosure: the AI-disclosure copy
// for a channel plus whether that channel hard-requires it before substantive
// conversation (voice) or treats it as voluntary (chat/sms).
type disclosureResponse struct {
	Channel   Channel `json:"channel"`
	Text      string  `json:"text"`
	Mandatory bool    `json:"mandatory"`
}

// handleDisclosure returns the AI-disclosure copy for a channel. GET
// /disclosure?channel=voice|chat|sms (defaults to voice — the stricter rule).
func (s *server) handleDisclosure(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return
	}
	ch := Channel(r.URL.Query().Get("channel"))
	switch ch {
	case ChannelVoice, ChannelChat, ChannelSMS:
		// recognized
	case "":
		ch = ChannelVoice // default to the strictest channel
	default:
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "unknown channel"})
		return
	}
	writeJSON(w, http.StatusOK, disclosureResponse{
		Channel:   ch,
		Text:      DisclosureText(ch),
		Mandatory: MandatoryDisclosure(ch),
	})
}

// newMux builds the HTTP routing for the conversation API plus /health.
func newMux(s *server) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"service": "voice", "status": "ok"})
	})
	mux.HandleFunc("/session", s.handleSession)
	// Subtree pattern; parseMessagePath validates the exact shape.
	mux.HandleFunc("/session/", s.handleMessage)
	mux.HandleFunc("/disclosure", s.handleDisclosure)
	return mux
}

func main() {
	addr := health.Getenv("VOICE_ADDR", ":8082")
	s := &server{manager: NewManager()}
	if url := os.Getenv("DOMAIN_URL"); url != "" {
		s.relay = HTTPRelay{URL: url, Token: os.Getenv("INBOUND_WEBHOOK_TOKEN")}
	}
	mux := newMux(s)
	log.Printf("voice listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}
