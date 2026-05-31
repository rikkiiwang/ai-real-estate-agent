// Command gateway is the public REST edge. It authenticates callers (U18) and
// fans out to internal gRPC services. For U1 it exposes a health check and a
// /valuation route that round-trips to the Python Brain over gRPC, proving the
// shared proto contract works across languages.
package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	realestatev1 "github.com/airealestate/realestate/proto/gen/go/realestate/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func main() {
	addr := getenv("GATEWAY_ADDR", ":8080")
	brainAddr := getenv("BRAIN_ADDR", "localhost:50051")

	// U18 trust boundary: the gateway fails fast if the auth secret is absent so
	// no protected route ever runs without a verifiable token.
	auth, err := NewAuthenticatorFromEnv()
	if err != nil {
		log.Fatalf("gateway auth: %v", err)
	}

	// Dev convenience: `gateway -mint-token <subject> <role>` prints a signed
	// token (used by scripts/smoke.sh and local testing) and exits.
	if len(os.Args) > 1 && os.Args[1] == "-mint-token" {
		subject, role := "dev", "user"
		if len(os.Args) > 2 {
			subject = os.Args[2]
		}
		if len(os.Args) > 3 {
			role = os.Args[3]
		}
		tok, err := auth.Issue(subject, role, time.Hour)
		if err != nil {
			log.Fatalf("mint-token: %v", err)
		}
		os.Stdout.WriteString(tok + "\n")
		return
	}

	mux := http.NewServeMux()

	// Root: a small API index so the bare URL is informative rather than a bare
	// 404. Unknown paths still 404 (this is an API, not a website).
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"service":     "ai-real-estate-agent gateway",
			"description": "Public REST edge for the AI Real Estate Agent (Austin).",
			"endpoints": map[string]string{
				"GET /health":             "liveness (open)",
				"GET /valuation?address=": "real-time home valuation (requires Bearer token)",
			},
		})
	})

	// /health stays open (no auth) for liveness probes.
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"service": "gateway", "status": "ok"})
	})

	// /valuation is behind the auth middleware: a valid Bearer token is required.
	mux.HandleFunc("/valuation", RequireAuth(auth, "", func(w http.ResponseWriter, r *http.Request) {
		address := r.URL.Query().Get("address")
		if address == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "address required"})
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
		defer cancel()

		// The gateway identifies itself to the brain with a signed service token,
		// so the brain can reject unauthenticated peers (server interceptor).
		conn, err := grpc.NewClient(brainAddr,
			grpc.WithTransportCredentials(insecure.NewCredentials()),
			grpc.WithUnaryInterceptor(ServiceTokenUnaryClientInterceptor(func() (string, error) {
				return auth.Issue("gateway", "service", time.Minute)
			})),
		)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": "brain dial failed"})
			return
		}
		defer conn.Close()

		client := realestatev1.NewValuationClient(conn)
		resp, err := client.GetValuation(ctx, &realestatev1.GetValuationRequest{Address: address})
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, resp)
	}))

	log.Printf("gateway listening on %s (brain=%s)", addr, brainAddr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatal(err)
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
