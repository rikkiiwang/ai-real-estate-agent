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

// HTTPRelay posts to <DOMAIN_URL>/inbound/voice with the shared webhook token so
// a phone call joins the same durable cross-channel thread (R4).
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
