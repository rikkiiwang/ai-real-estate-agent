// Command ingestion pulls real Travis County GIS + TCAD data and serves
// synthetic RESO-shaped listings behind a swappable ListingSource (U2).
// For U1 it boots with a health check.
package main

import (
	"log"

	"github.com/airealestate/realestate/internal/health"
)

func main() {
	addr := health.Getenv("INGESTION_ADDR", ":8081")
	log.Fatal(health.Serve("ingestion", addr))
}
