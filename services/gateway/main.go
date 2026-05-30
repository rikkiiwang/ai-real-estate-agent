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

	mux := http.NewServeMux()

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"service": "gateway", "status": "ok"})
	})

	mux.HandleFunc("/valuation", func(w http.ResponseWriter, r *http.Request) {
		address := r.URL.Query().Get("address")
		if address == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "address required"})
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel()

		conn, err := grpc.NewClient(brainAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
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
	})

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
