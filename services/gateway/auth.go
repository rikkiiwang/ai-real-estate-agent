// auth.go implements the gateway's authentication primitives (U18): a
// stdlib-only, HMAC-SHA256 signed token in a compact `header.payload.signature`
// form (each segment base64url, no padding). The token carries a subject, a
// role, and an expiry; verification checks the signature with a constant-time
// compare and rejects expired tokens. No JWT library or third-party dependency
// is used — only crypto/hmac, crypto/sha256, encoding/base64, encoding/json.
//
// The same primitive backs two trust boundaries: authenticated REST sessions at
// the public edge (see authz.go) and signed service tokens on internal gRPC
// hops (see the interceptors in authz.go).
package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"
)

// Token verification / parsing errors. Callers compare against these so HTTP and
// gRPC layers can map them to the right status without string matching.
var (
	// ErrNoSecret is returned when GATEWAY_AUTH_SECRET is unset or empty.
	ErrNoSecret = errors.New("auth: GATEWAY_AUTH_SECRET is not set")
	// ErrMalformedToken is returned when a token is not three base64url segments.
	ErrMalformedToken = errors.New("auth: malformed token")
	// ErrBadSignature is returned when the HMAC signature does not match.
	ErrBadSignature = errors.New("auth: signature mismatch")
	// ErrExpiredToken is returned when the token's expiry is in the past.
	ErrExpiredToken = errors.New("auth: token expired")
)

// tokenHeader names the algorithm so the format can evolve without ambiguity.
type tokenHeader struct {
	Alg string `json:"alg"`
	Typ string `json:"typ"`
}

// Claims is the verified payload carried by a signed token: who the caller is
// (Subject), what they may do (Role), and until when the token is valid
// (ExpiresAt, Unix seconds). IssuedAt is informational.
type Claims struct {
	Subject   string `json:"sub"`
	Role      string `json:"role"`
	IssuedAt  int64  `json:"iat"`
	ExpiresAt int64  `json:"exp"`
}

// Authenticator signs and verifies tokens with a shared HMAC secret. It is safe
// for concurrent use: the secret is immutable after construction.
type Authenticator struct {
	secret []byte
}

// NewAuthenticator builds an Authenticator from an explicit secret. The secret
// must be non-empty; an empty secret would make every token trivially forgeable.
func NewAuthenticator(secret []byte) (*Authenticator, error) {
	if len(secret) == 0 {
		return nil, ErrNoSecret
	}
	return &Authenticator{secret: secret}, nil
}

// NewAuthenticatorFromEnv reads the HMAC secret from GATEWAY_AUTH_SECRET. It
// returns ErrNoSecret with a clear message when the variable is unset, so the
// gateway fails fast at startup rather than silently accepting any token.
func NewAuthenticatorFromEnv() (*Authenticator, error) {
	secret := os.Getenv("GATEWAY_AUTH_SECRET")
	if secret == "" {
		return nil, ErrNoSecret
	}
	return NewAuthenticator([]byte(secret))
}

// b64 is base64url without padding, matching the JWT-style compact encoding.
var b64 = base64.RawURLEncoding

// sign computes the HMAC-SHA256 of "header.payload" and returns its base64url
// encoding (the signature segment).
func (a *Authenticator) sign(signingInput string) string {
	mac := hmac.New(sha256.New, a.secret)
	mac.Write([]byte(signingInput))
	return b64.EncodeToString(mac.Sum(nil))
}

// Issue mints a signed token for subject/role valid for ttl from now.
func (a *Authenticator) Issue(subject, role string, ttl time.Duration) (string, error) {
	now := time.Now()
	return a.issueAt(subject, role, now, now.Add(ttl))
}

// issueAt is the deterministic core of Issue, taking explicit timestamps so
// tests can mint already-expired tokens.
func (a *Authenticator) issueAt(subject, role string, issued, expires time.Time) (string, error) {
	header, err := json.Marshal(tokenHeader{Alg: "HS256", Typ: "JWT"})
	if err != nil {
		return "", err
	}
	payload, err := json.Marshal(Claims{
		Subject:   subject,
		Role:      role,
		IssuedAt:  issued.Unix(),
		ExpiresAt: expires.Unix(),
	})
	if err != nil {
		return "", err
	}
	signingInput := b64.EncodeToString(header) + "." + b64.EncodeToString(payload)
	return signingInput + "." + a.sign(signingInput), nil
}

// Verify checks a token's signature and expiry and returns its claims. It uses a
// constant-time comparison on the signature to avoid timing leaks, and treats a
// missing/short token as malformed.
func (a *Authenticator) Verify(token string) (*Claims, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 || parts[0] == "" || parts[1] == "" || parts[2] == "" {
		return nil, ErrMalformedToken
	}
	signingInput := parts[0] + "." + parts[1]

	expectedSig := a.sign(signingInput)
	if !hmac.Equal([]byte(expectedSig), []byte(parts[2])) {
		return nil, ErrBadSignature
	}

	payloadBytes, err := b64.DecodeString(parts[1])
	if err != nil {
		return nil, fmt.Errorf("%w: payload not base64url", ErrMalformedToken)
	}
	var claims Claims
	if err := json.Unmarshal(payloadBytes, &claims); err != nil {
		return nil, fmt.Errorf("%w: payload not json", ErrMalformedToken)
	}
	if claims.ExpiresAt > 0 && time.Now().Unix() >= claims.ExpiresAt {
		return nil, ErrExpiredToken
	}
	return &claims, nil
}
