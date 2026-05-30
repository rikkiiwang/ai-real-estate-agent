// Command ingestion pulls real Travis County GIS + TCAD data and serves
// synthetic RESO-shaped listings behind a swappable ListingSource (U2).
package main

// PropertyRecord is the normalized property record emitted by ingestion. It is
// the join of a Travis County GIS parcel (geometry + attributes) and a TCAD
// appraisal record, keyed on parcel/account number. U5 persists these into the
// pgvector source store; here they live in an in-memory SourceStore.
type PropertyRecord struct {
	ParcelID      string  // GIS parcel id / TCAD property (account) number
	Address       string  // situs address
	Latitude      float64 // parcel centroid
	Longitude     float64
	LandValue     int // USD, from TCAD
	ImprovementValue int // USD, from TCAD
	AppraisedValue int // USD, from TCAD
	YearBuilt      int
	LivingArea     int // square feet, from TCAD
	// Sources lists the provenance kinds that contributed to this record, so
	// the Critic/Lawyer layer can cite where each fact came from.
	Sources []string
}

// ListingRecord is a normalized listing emitted by a ListingSource. It mirrors
// the RESO-shaped synthetic Listing but is decoupled from the data/synthetic
// package so alternative sources (a real RESO feed) can produce it too.
type ListingRecord struct {
	ListingKey string
	Address    string
	City       string
	State      string
	PostalCode string
	Beds       int
	Baths      int
	LivingArea int
	ListPrice  int
	Latitude   float64
	Longitude  float64
	Photos     []string
}
