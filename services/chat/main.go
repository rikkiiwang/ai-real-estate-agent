// Command chat is the standalone consumer-facing web app: a chat surface where
// a seller/buyer talks to the AI agent and WATCHES it reason over live data.
//
// It is a first-party frontend, so — like the gateway — it talks to the Brain
// over the internal gRPC mesh (Conversation.Orchestrate) and reshapes the full
// reasoning trace into a clean payload the browser SPA renders: the grounded,
// cited answer plus the generate→critique→fair-housing→decide timeline,
// per-claim verdicts + citations, the composite-confidence sub-signals, and the
// human-handoff decision. The browser only ever talks to this server.
package main

import (
	"context"
	"embed"
	"encoding/json"
	"io/fs"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	realestatev1 "github.com/airealestate/realestate/proto/gen/go/realestate/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

//go:embed static
var staticFS embed.FS

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// --- UI payload (decoupled from proto field casing) -------------------------

type claimDTO struct {
	Claim     string  `json:"claim"`
	Label     string  `json:"label"`     // entailed | contradicted | baseless
	Score     float64 `json:"score"`     // 0..1 entailment confidence
	Citation  string  `json:"citation"`  // source id (when entailed)
	Source    string  `json:"source"`    // provenance kind
	Supported bool    `json:"supported"` // entailed AND cited
	Reason    string  `json:"reason"`
}

type stepDTO struct {
	Node   string `json:"node"`
	Title  string `json:"title"`
	Detail string `json:"detail"`
	Status string `json:"status"` // ok | warn | block
}

type chatResponse struct {
	Outcome      string     `json:"outcome"`  // send | handoff
	Escalated    bool       `json:"escalated"`
	Message      string     `json:"message"`  // what the user is shown
	Draft        string     `json:"draft"`
	Sufficient   bool       `json:"sufficient_data"`
	Attempts     int32      `json:"attempts"`
	Confidence   float64    `json:"confidence"`
	VerifyReason string     `json:"verify_reason"`
	Coverage     float64    `json:"coverage"`
	Agreement    float64    `json:"agreement"`
	SelfConsist  float64    `json:"self_consistency"`
	FHAllowed    bool       `json:"fair_housing_allowed"`
	FHReason     string     `json:"fair_housing_reason"`
	Handoff      *handoffDTO `json:"handoff,omitempty"`
	Citations    []string   `json:"citations"`
	Claims       []claimDTO `json:"claims"`
	Steps        []stepDTO  `json:"steps"`
}

type handoffDTO struct {
	Trigger     string `json:"trigger"`
	Reason      string `json:"reason"`
	Recommended string `json:"recommended_action"`
	Hard        bool   `json:"hard_trigger"`
}

func main() {
	port := getenv("PORT", "8080")
	brainAddr := getenv("BRAIN_ADDR", "localhost:50051")

	sub, err := fs.Sub(staticFS, "static")
	if err != nil {
		log.Fatalf("static fs: %v", err)
	}

	mux := http.NewServeMux()
	mux.Handle("/", http.FileServer(http.FS(sub)))
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"service": "chat", "status": "ok"})
	})
	mux.HandleFunc("/api/chat", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST only"})
			return
		}
		var body struct {
			Address  string `json:"address"`
			Query    string `json:"query"`
			ThreadID string `json:"thread_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
			return
		}
		body.Address, body.Query = strings.TrimSpace(body.Address), strings.TrimSpace(body.Query)
		if body.Address == "" || body.Query == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "address and query are required"})
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), 45*time.Second)
		defer cancel()

		conn, err := grpc.NewClient(brainAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": "agent unavailable"})
			return
		}
		defer conn.Close()

		client := realestatev1.NewConversationClient(conn)
		resp, err := client.Orchestrate(ctx, &realestatev1.OrchestrateRequest{
			Address:  body.Address,
			Query:    body.Query,
			ThreadId: body.ThreadID,
		})
		if err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": "the agent could not complete this turn"})
			return
		}
		writeJSON(w, http.StatusOK, toChatResponse(resp))
	})

	log.Printf("chat app listening on :%s (brain=%s)", port, brainAddr)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal(err)
	}
}

// toChatResponse reshapes the orchestrator's proto result into the browser DTO,
// and composes the user-facing message (the cited answer on send, or a candid
// "I'm bringing in a licensed human" note on a handoff — never a fabricated
// number).
func toChatResponse(r *realestatev1.OrchestrateResponse) chatResponse {
	claims := make([]claimDTO, 0, len(r.GetClaims()))
	for _, c := range r.GetClaims() {
		claims = append(claims, claimDTO{
			Claim:     c.GetClaim(),
			Label:     strings.ToLower(c.GetLabel()),
			Score:     c.GetScore(),
			Citation:  c.GetCitationSourceId(),
			Source:    c.GetSourceKind(),
			Supported: c.GetSupported(),
			Reason:    c.GetReason(),
		})
	}
	steps := make([]stepDTO, 0, len(r.GetSteps()))
	for _, s := range r.GetSteps() {
		steps = append(steps, stepDTO{
			Node:   s.GetNode(),
			Title:  s.GetTitle(),
			Detail: s.GetDetail(),
			Status: s.GetStatus(),
		})
	}

	out := chatResponse{
		Outcome:      r.GetOutcome(),
		Escalated:    r.GetEscalated(),
		Draft:        r.GetDraft(),
		Sufficient:   r.GetSufficientData(),
		Attempts:     r.GetAttempts(),
		Confidence:   r.GetConfidence(),
		VerifyReason: r.GetVerificationReason(),
		Coverage:     r.GetCoverage(),
		Agreement:    r.GetAgreement(),
		SelfConsist:  r.GetSelfConsistency(),
		FHAllowed:    r.GetFairHousingAllowed(),
		FHReason:     r.GetFairHousingReason(),
		Citations:    r.GetCitations(),
		Claims:       claims,
		Steps:        steps,
	}

	if r.GetEscalated() {
		out.Handoff = &handoffDTO{
			Trigger:     r.GetHandoffTrigger(),
			Reason:      r.GetHandoffReason(),
			Recommended: r.GetHandoffRecommendedAction(),
			Hard:        r.GetHardTrigger(),
		}
		out.Message = handoffMessage(r)
	} else {
		out.Message = r.GetFinalMessage()
	}
	return out
}

// handoffMessage is the candid, consumer-facing note shown when the agent
// declines to answer on its own and routes to a licensed human broker.
func handoffMessage(r *realestatev1.OrchestrateResponse) string {
	switch r.GetHandoffTrigger() {
	case "legal_complexity_upl":
		return "That touches contract or legal wording, which I'm not licensed to draft. " +
			"I'm connecting you with a licensed human broker who can handle it properly."
	case "explicit_human_request":
		return "Of course — I'm connecting you with a licensed human broker now."
	case "hostile_or_distressed_sentiment":
		return "I want to make sure you're taken care of, so I'm bringing in a licensed human broker to help directly."
	case "fair_housing_rail_trip":
		return "I can't answer that the way it was asked without risking a Fair Housing violation, " +
			"so I'm routing this to a licensed human broker for a compliant response."
	default:
		if !r.GetSufficientData() {
			return "I don't have enough verified source data on that property to answer responsibly, " +
				"so rather than guess, I'm handing this to a licensed human broker to look into."
		}
		return "I'm not confident enough in a verified answer here, so I'm routing this to a " +
			"licensed human broker rather than risk telling you something unsupported."
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
