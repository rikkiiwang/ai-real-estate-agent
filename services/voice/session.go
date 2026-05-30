// Package main — Voice transport (U11).
//
// session.go holds the in-memory Session manager that gives the single-channel
// conversation its thread/context continuity: sessions are keyed by id and hold
// the running conversation thread (ordered turns) plus the neutral fields the
// channel has collected so far. The Manager is concurrency-safe so the HTTP
// transport in main.go can serve many conversations at once.
//
// The Session contract here is channel-agnostic on purpose: a turn carries a
// role and text, and additional channels (SMS, email, voice) attach to the same
// Session/Manager contract later without changing it.
package main

import (
	"crypto/rand"
	"encoding/hex"
	"sync"
	"time"
)

// Role identifies who produced a turn in the conversation thread.
type Role string

const (
	// RoleSeller is a turn from the consumer (the seller side for U11).
	RoleSeller Role = "seller"
	// RoleAgent is a turn from the AI agent.
	RoleAgent Role = "agent"
)

// Turn is one message in the conversation thread. It is channel-agnostic: only
// a role and text, so any channel can append to the same thread.
type Turn struct {
	Role Role      `json:"role"`
	Text string    `json:"text"`
	At   time.Time `json:"at"`
}

// Session is one continuous conversation. It owns the ordered thread of turns
// and the neutral, transaction-relevant fields collected so far (address,
// timeline, motivation, ...). Fields holds ONLY neutral signals — the
// qualification in qualify.go never reads protected-class or proxy data.
type Session struct {
	ID        string            `json:"id"`
	Thread    []Turn            `json:"thread"`
	Fields    map[string]string `json:"fields"`
	CreatedAt time.Time         `json:"created_at"`
	UpdatedAt time.Time         `json:"updated_at"`
}

// snapshot returns a deep copy so callers (and JSON encoders running outside the
// lock) never observe a session being mutated concurrently.
func (s *Session) snapshot() Session {
	thread := make([]Turn, len(s.Thread))
	copy(thread, s.Thread)
	fields := make(map[string]string, len(s.Fields))
	for k, v := range s.Fields {
		fields[k] = v
	}
	return Session{
		ID:        s.ID,
		Thread:    thread,
		Fields:    fields,
		CreatedAt: s.CreatedAt,
		UpdatedAt: s.UpdatedAt,
	}
}

// Manager is a concurrency-safe, in-memory store of sessions keyed by id. It is
// the thread/context-continuity backbone: the same session id across requests
// returns the same growing thread.
type Manager struct {
	mu       sync.Mutex
	sessions map[string]*Session
	now      func() time.Time // injectable clock (tests)
	newID    func() string    // injectable id source (tests)
}

// NewManager builds an empty session Manager with real wall-clock + random ids.
func NewManager() *Manager {
	return &Manager{
		sessions: make(map[string]*Session),
		now:      time.Now,
		newID:    newID,
	}
}

// newID returns a random hex session id.
func newID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		// rand.Read failing is fatal-rare; fall back to a time-seeded id so the
		// transport never panics on session creation.
		return hex.EncodeToString([]byte(time.Now().Format(time.RFC3339Nano)))
	}
	return hex.EncodeToString(b)
}

// Start creates and stores a new empty session, returning a snapshot of it.
func (m *Manager) Start() Session {
	m.mu.Lock()
	defer m.mu.Unlock()
	t := m.now()
	s := &Session{
		ID:        m.newID(),
		Thread:    []Turn{},
		Fields:    map[string]string{},
		CreatedAt: t,
		UpdatedAt: t,
	}
	m.sessions[s.ID] = s
	return s.snapshot()
}

// AppendTurn appends a turn to the session's thread, merges any collected
// neutral fields, and returns a snapshot of the updated session. ok is false if
// no session with id exists. fields may be nil; only non-empty values merge.
func (m *Manager) AppendTurn(id string, role Role, text string, fields map[string]string) (Session, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	s, exists := m.sessions[id]
	if !exists {
		return Session{}, false
	}
	now := m.now()
	s.Thread = append(s.Thread, Turn{Role: role, Text: text, At: now})
	for k, v := range fields {
		if v == "" {
			continue
		}
		s.Fields[k] = v
	}
	s.UpdatedAt = now
	return s.snapshot(), true
}

// Get returns a snapshot of the session, or ok=false if absent.
func (m *Manager) Get(id string) (Session, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	s, exists := m.sessions[id]
	if !exists {
		return Session{}, false
	}
	return s.snapshot(), true
}
