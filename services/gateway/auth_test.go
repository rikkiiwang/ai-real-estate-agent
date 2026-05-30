package main

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	realestatev1 "github.com/airealestate/realestate/proto/gen/go/realestate/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
)

func testAuth(t *testing.T) *Authenticator {
	t.Helper()
	a, err := NewAuthenticator([]byte("test-secret-do-not-commit"))
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func TestNewAuthenticatorRequiresSecret(t *testing.T) {
	if _, err := NewAuthenticator(nil); err != ErrNoSecret {
		t.Fatalf("expected ErrNoSecret, got %v", err)
	}
	t.Setenv("GATEWAY_AUTH_SECRET", "")
	if _, err := NewAuthenticatorFromEnv(); err != ErrNoSecret {
		t.Fatalf("expected ErrNoSecret from env, got %v", err)
	}
	t.Setenv("GATEWAY_AUTH_SECRET", "abc")
	if _, err := NewAuthenticatorFromEnv(); err != nil {
		t.Fatalf("unexpected err with secret set: %v", err)
	}
}

func TestTokenRoundTrip(t *testing.T) {
	a := testAuth(t)
	tok, err := a.Issue("alice", "agent", time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	claims, err := a.Verify(tok)
	if err != nil {
		t.Fatalf("verify: %v", err)
	}
	if claims.Subject != "alice" || claims.Role != "agent" {
		t.Fatalf("unexpected claims: %+v", claims)
	}
}

func TestVerifyRejectsTamperedSignature(t *testing.T) {
	a := testAuth(t)
	tok, _ := a.Issue("alice", "agent", time.Minute)
	if _, err := a.Verify(tok + "x"); err != ErrBadSignature {
		t.Fatalf("expected ErrBadSignature, got %v", err)
	}
	// A token signed by a different secret must not verify.
	other, _ := NewAuthenticator([]byte("different"))
	otherTok, _ := other.Issue("alice", "agent", time.Minute)
	if _, err := a.Verify(otherTok); err != ErrBadSignature {
		t.Fatalf("expected ErrBadSignature for foreign token, got %v", err)
	}
}

func TestVerifyRejectsMalformed(t *testing.T) {
	a := testAuth(t)
	for _, tok := range []string{"", "a.b", "a.b.c.d", "..", "onlyonepart"} {
		if _, err := a.Verify(tok); err != ErrMalformedToken && err != ErrBadSignature {
			t.Fatalf("token %q: expected malformed/bad-sig, got %v", tok, err)
		}
	}
}

func TestVerifyRejectsExpired(t *testing.T) {
	a := testAuth(t)
	past := time.Now().Add(-2 * time.Hour)
	tok, err := a.issueAt("alice", "agent", past, past.Add(time.Hour))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := a.Verify(tok); err != ErrExpiredToken {
		t.Fatalf("expected ErrExpiredToken, got %v", err)
	}
}

// --- HTTP middleware coverage (U18 critical scenarios) ---

func TestHealthOpenWithoutAuth(t *testing.T) {
	a := testAuth(t)
	mux := newAuthGatewayMux("unused", a, "")
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/health", nil))
	if rr.Code != http.StatusOK {
		t.Fatalf("health should be open, got %d", rr.Code)
	}
}

func TestProtectedRouteRejectsMissingToken(t *testing.T) {
	a := testAuth(t)
	mux := newAuthGatewayMux("unused", a, "")
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/valuation?address=x", nil))
	if rr.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for missing token, got %d", rr.Code)
	}
}

func TestProtectedRouteRejectsInvalidAndExpiredToken(t *testing.T) {
	a := testAuth(t)
	mux := newAuthGatewayMux("unused", a, "")

	// Invalid (tampered) token.
	bad, _ := a.Issue("alice", "agent", time.Minute)
	req := httptest.NewRequest(http.MethodGet, "/valuation?address=x", nil)
	req.Header.Set("Authorization", "Bearer "+bad+"tamper")
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for invalid token, got %d", rr.Code)
	}

	// Expired token.
	past := time.Now().Add(-time.Hour)
	exp, _ := a.issueAt("alice", "agent", past, past.Add(time.Minute))
	req = httptest.NewRequest(http.MethodGet, "/valuation?address=x", nil)
	req.Header.Set("Authorization", "Bearer "+exp)
	rr = httptest.NewRecorder()
	mux.ServeHTTP(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for expired token, got %d", rr.Code)
	}
}

func TestProtectedRouteAllowsValidToken(t *testing.T) {
	a := testAuth(t)
	brainAddr := startFakeBrain(t)
	mux := newAuthGatewayMux(brainAddr, a, "")

	tok, _ := a.Issue("alice", "agent", time.Minute)
	req := httptest.NewRequest(http.MethodGet, "/valuation?address=123+Congress", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200 with valid token, got %d body=%s", rr.Code, rr.Body.String())
	}
}

func TestProtectedRouteEnforcesRole(t *testing.T) {
	a := testAuth(t)
	mux := newAuthGatewayMux("unused", a, "admin")

	tok, _ := a.Issue("alice", "agent", time.Minute) // wrong role
	req := httptest.NewRequest(http.MethodGet, "/valuation?address=x", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, req)
	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403 for wrong role, got %d", rr.Code)
	}
}

// --- gRPC interceptor coverage ---

// startAuthedBrain stands up a fake Valuation server guarded by the service-token
// server interceptor and returns its address.
func startAuthedBrain(t *testing.T, a *Authenticator) string {
	t.Helper()
	lis, err := net.Listen("tcp", "localhost:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := grpc.NewServer(grpc.UnaryInterceptor(ServiceTokenUnaryServerInterceptor(a)))
	realestatev1.RegisterValuationServer(srv, fakeValuation{})
	go srv.Serve(lis)
	t.Cleanup(srv.Stop)
	return lis.Addr().String()
}

func TestGRPCRejectsCallWithoutServiceToken(t *testing.T) {
	a := testAuth(t)
	addr := startAuthedBrain(t, a)

	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_, err = realestatev1.NewValuationClient(conn).GetValuation(ctx, &realestatev1.GetValuationRequest{Address: "x"})
	if status.Code(err) != codes.Unauthenticated {
		t.Fatalf("expected Unauthenticated, got %v", err)
	}
}

func TestGRPCAllowsCallWithValidServiceToken(t *testing.T) {
	a := testAuth(t)
	addr := startAuthedBrain(t, a)

	conn, err := grpc.NewClient(addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithUnaryInterceptor(ServiceTokenUnaryClientInterceptor(func() (string, error) {
			return a.Issue("gateway", "service", time.Minute)
		})),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	resp, err := realestatev1.NewValuationClient(conn).GetValuation(ctx, &realestatev1.GetValuationRequest{Address: "123 Congress"})
	if err != nil {
		t.Fatalf("expected OK with valid service token, got %v", err)
	}
	if !resp.SufficientData {
		t.Fatalf("unexpected response: %+v", resp)
	}
}

func TestGRPCRejectsForeignServiceToken(t *testing.T) {
	a := testAuth(t)
	addr := startAuthedBrain(t, a)
	foreign, _ := NewAuthenticator([]byte("attacker-secret"))

	conn, err := grpc.NewClient(addr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithUnaryInterceptor(ServiceTokenUnaryClientInterceptor(func() (string, error) {
			return foreign.Issue("attacker", "service", time.Minute)
		})),
	)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_, err = realestatev1.NewValuationClient(conn).GetValuation(ctx, &realestatev1.GetValuationRequest{Address: "x"})
	if status.Code(err) != codes.Unauthenticated {
		t.Fatalf("expected Unauthenticated for foreign token, got %v", err)
	}
}
