// Package health provides a minimal HTTP health endpoint shared by the Go
// services (gateway, ingestion, voice).
package health

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
)

// Getenv returns the env var k or def when unset.
func Getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// Serve starts an HTTP server on addr exposing GET /health for the named
// service. It blocks until the server exits.
func Serve(service, addr string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]string{"service": service, "status": "ok"})
	})
	log.Printf("%s listening on %s", service, addr)
	return http.ListenAndServe(addr, mux)
}
