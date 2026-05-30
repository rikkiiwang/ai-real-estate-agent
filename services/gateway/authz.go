// authz.go wires the auth primitives (auth.go) into the two trust boundaries of
// U18: HTTP middleware that protects REST routes at the public edge, and gRPC
// interceptors that attach/require a signed service token on every internal hop.
// Together they ensure no REST or gRPC path is reachable unauthenticated and
// that per-route authorization (role checks) is enforced.
package main

import (
	"context"
	"net/http"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

// claimsContextKey is the unexported context key under which verified Claims are
// stashed by RequireAuth, so downstream handlers can read the caller identity.
type claimsContextKey struct{}

// ClaimsFromContext returns the verified Claims attached by RequireAuth, if any.
func ClaimsFromContext(ctx context.Context) (*Claims, bool) {
	c, ok := ctx.Value(claimsContextKey{}).(*Claims)
	return c, ok
}

// bearerToken extracts the token from an "Authorization: Bearer <token>" header.
func bearerToken(r *http.Request) (string, bool) {
	h := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if len(h) <= len(prefix) || !strings.EqualFold(h[:len(prefix)], prefix) {
		return "", false
	}
	return strings.TrimSpace(h[len(prefix):]), true
}

// RequireAuth wraps a handler so it only runs for requests carrying a valid
// Bearer token. Missing, malformed, expired, or badly signed tokens all yield
// 401. When requiredRole is non-empty, the token's role must match exactly or
// the request is denied with 403. Verified claims are placed on the request
// context for the wrapped handler.
func RequireAuth(auth *Authenticator, requiredRole string, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		token, ok := bearerToken(r)
		if !ok {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "missing bearer token"})
			return
		}
		claims, err := auth.Verify(token)
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid token"})
			return
		}
		if requiredRole != "" && claims.Role != requiredRole {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "insufficient role"})
			return
		}
		ctx := context.WithValue(r.Context(), claimsContextKey{}, claims)
		next(w, r.WithContext(ctx))
	}
}

// serviceTokenMetadataKey is the gRPC metadata key carrying the signed service
// token on internal calls. gRPC lower-cases metadata keys; we keep it lowercase.
const serviceTokenMetadataKey = "authorization"

// ServiceTokenUnaryClientInterceptor attaches a freshly signed service token to
// the outbound metadata of every unary gRPC call, identifying this process to
// its peers. The token is minted per call from the supplied closure so callers
// control subject/role/ttl (and so expiry stays fresh).
func ServiceTokenUnaryClientInterceptor(mint func() (string, error)) grpc.UnaryClientInterceptor {
	return func(ctx context.Context, method string, req, reply any, cc *grpc.ClientConn, invoker grpc.UnaryInvoker, opts ...grpc.CallOption) error {
		token, err := mint()
		if err != nil {
			return status.Errorf(codes.Unauthenticated, "service token: %v", err)
		}
		ctx = metadata.AppendToOutgoingContext(ctx, serviceTokenMetadataKey, "Bearer "+token)
		return invoker(ctx, method, req, reply, cc, opts...)
	}
}

// ServiceTokenUnaryServerInterceptor rejects any unary call whose metadata lacks
// a valid signed service token with codes.Unauthenticated, so no service is
// reachable by an unauthenticated peer. Verified claims are placed on the
// handler context.
func ServiceTokenUnaryServerInterceptor(auth *Authenticator) grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
		md, ok := metadata.FromIncomingContext(ctx)
		if !ok {
			return nil, status.Error(codes.Unauthenticated, "missing metadata")
		}
		vals := md.Get(serviceTokenMetadataKey)
		if len(vals) == 0 {
			return nil, status.Error(codes.Unauthenticated, "missing service token")
		}
		token := strings.TrimSpace(vals[0])
		token = strings.TrimPrefix(token, "Bearer ")
		token = strings.TrimPrefix(token, "bearer ")
		claims, err := auth.Verify(token)
		if err != nil {
			return nil, status.Errorf(codes.Unauthenticated, "invalid service token: %v", err)
		}
		ctx = context.WithValue(ctx, claimsContextKey{}, claims)
		return handler(ctx, req)
	}
}
