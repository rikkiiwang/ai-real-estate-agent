package main

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"

	realestatev1 "github.com/airealestate/realestate/proto/gen/go/realestate/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// fakeValuation is an in-process Go implementation of the Valuation service,
// letting the gateway's gRPC client + handler be tested deterministically in CI
// without standing up the Python brain. The cross-language path is covered by
// scripts/smoke.sh.
type fakeValuation struct {
	realestatev1.UnimplementedValuationServer
}

func (fakeValuation) GetValuation(_ context.Context, req *realestatev1.GetValuationRequest) (*realestatev1.GetValuationResponse, error) {
	if req.Address == "" {
		return &realestatev1.GetValuationResponse{SufficientData: false}, nil
	}
	return &realestatev1.GetValuationResponse{
		SufficientData: true,
		Estimate:       400000,
		Low:            380000,
		High:           420000,
		Facts:          []*realestatev1.SourceFact{{SourceId: "test", Kind: "test", Description: "ok"}},
	}, nil
}

func startFakeBrain(t *testing.T) string {
	t.Helper()
	lis, err := net.Listen("tcp", "localhost:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := grpc.NewServer()
	realestatev1.RegisterValuationServer(srv, fakeValuation{})
	go srv.Serve(lis)
	t.Cleanup(srv.Stop)
	return lis.Addr().String()
}

// valuationHandler is the shared /valuation logic used by both the auth-optional
// newGatewayMux (existing round-trip tests) and the authenticated mux.
func valuationHandler(brainAddr string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		address := r.URL.Query().Get("address")
		if address == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "address required"})
			return
		}
		conn, err := grpc.NewClient(brainAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": "dial"})
			return
		}
		defer conn.Close()
		resp, err := realestatev1.NewValuationClient(conn).GetValuation(r.Context(), &realestatev1.GetValuationRequest{Address: address})
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, resp)
	}
}

// newGatewayMux is the auth-optional mux retained so the existing health and
// round-trip tests exercise the handler logic without minting tokens.
func newGatewayMux(brainAddr string) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"service": "gateway", "status": "ok"})
	})
	mux.HandleFunc("/valuation", valuationHandler(brainAddr))
	return mux
}

// newAuthGatewayMux mirrors main()'s wiring: /health open, /valuation behind the
// auth middleware. requiredRole may be "" for any-authenticated.
func newAuthGatewayMux(brainAddr string, auth *Authenticator, requiredRole string) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"service": "gateway", "status": "ok"})
	})
	mux.HandleFunc("/valuation", RequireAuth(auth, requiredRole, valuationHandler(brainAddr)))
	return mux
}

func TestHealth(t *testing.T) {
	mux := newGatewayMux("unused")
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/health", nil))
	if rr.Code != http.StatusOK {
		t.Fatalf("health status = %d", rr.Code)
	}
}

func TestValuationRoundTrip(t *testing.T) {
	brainAddr := startFakeBrain(t)
	mux := newGatewayMux(brainAddr)

	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/valuation?address=123+Congress", nil))
	if rr.Code != http.StatusOK {
		t.Fatalf("valuation status = %d body=%s", rr.Code, rr.Body.String())
	}
	var resp realestatev1.GetValuationResponse
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	if !resp.SufficientData || resp.Estimate <= 0 {
		t.Fatalf("unexpected valuation: %+v", &resp)
	}
}

func TestValuationRequiresAddress(t *testing.T) {
	mux := newGatewayMux("unused")
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/valuation", nil))
	if rr.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rr.Code)
	}
}
