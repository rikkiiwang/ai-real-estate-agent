// Command voice is the single-channel conversation transport (U11). It holds
// channel sessions and thread continuity, architected so additional channels
// attach to the same session contract. For U1 it boots with a health check.
package main

import (
	"log"

	"github.com/airealestate/realestate/internal/health"
)

func main() {
	addr := health.Getenv("VOICE_ADDR", ":8082")
	log.Fatal(health.Serve("voice", addr))
}
