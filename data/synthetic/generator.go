// Package synthetic generates deterministic, RESO-Data-Dictionary-shaped
// listings for Austin, Travis County. It is the MVP stand-in for a real
// MLS/RESO feed (a live Bridge/RESO feed is deferred; see U2). Generation is
// seeded so the output is stable across runs, which keeps ingestion tests
// deterministic.
package synthetic

import (
	"fmt"
	"math/rand"
)

// Listing is a normalized listing record shaped after the RESO Data
// Dictionary. Field names mirror RESO standard names (UnparsedAddress,
// BedroomsTotal, BathroomsTotalInteger, LivingArea, ListPrice, Latitude,
// Longitude, Media) so a real RESO feed can populate the same struct later.
type Listing struct {
	ListingKey            string   `json:"ListingKey"`
	UnparsedAddress       string   `json:"UnparsedAddress"`
	City                  string   `json:"City"`
	StateOrProvince       string   `json:"StateOrProvince"`
	PostalCode            string   `json:"PostalCode"`
	BedroomsTotal         int      `json:"BedroomsTotal"`
	BathroomsTotalInteger int      `json:"BathroomsTotalInteger"`
	LivingArea            int      `json:"LivingArea"` // square feet
	ListPrice             int      `json:"ListPrice"`  // USD
	Latitude              float64  `json:"Latitude"`
	Longitude             float64  `json:"Longitude"`
	Media                 []string `json:"Media"` // photo URLs
}

// austinZIPs are real Travis County / Austin postal codes; the centroid map
// gives each a plausible lat/long so generated coordinates land in-county.
var austinZIPs = []string{"78701", "78702", "78703", "78704", "78745", "78751", "78759"}

var zipCentroids = map[string]struct{ lat, lng float64 }{
	"78701": {30.2711, -97.7437},
	"78702": {30.2613, -97.7142},
	"78703": {30.2939, -97.7649},
	"78704": {30.2434, -97.7698},
	"78745": {30.2070, -97.7950},
	"78751": {30.3050, -97.7236},
	"78759": {30.4055, -97.7506},
}

var streetNames = []string{
	"Congress Ave", "Guadalupe St", "Lamar Blvd", "Cesar Chavez St",
	"Manor Rd", "Burnet Rd", "Slaughter Ln", "Riverside Dr",
}

// Generate returns n deterministic RESO-shaped listings for the given seed.
// The same (seed, n) always yields the same listings.
func Generate(seed int64, n int) []Listing {
	r := rand.New(rand.NewSource(seed))
	listings := make([]Listing, 0, n)
	for i := 0; i < n; i++ {
		zip := austinZIPs[r.Intn(len(austinZIPs))]
		c := zipCentroids[zip]
		beds := 2 + r.Intn(4)              // 2..5
		baths := 1 + r.Intn(beds)          // 1..beds
		sqft := 800 + beds*250 + r.Intn(900)
		// Price loosely tracks size + a per-ZIP premium with noise.
		price := sqft*(250+r.Intn(250)) + r.Intn(50000)
		streetNum := 100 + r.Intn(8900)
		street := streetNames[r.Intn(len(streetNames))]
		addr := fmt.Sprintf("%d %s", streetNum, street)

		key := fmt.Sprintf("SYN-%08d", r.Int63n(100000000))
		listings = append(listings, Listing{
			ListingKey:            key,
			UnparsedAddress:       addr,
			City:                  "Austin",
			StateOrProvince:       "TX",
			PostalCode:            zip,
			BedroomsTotal:         beds,
			BathroomsTotalInteger: baths,
			LivingArea:            sqft,
			ListPrice:             price,
			// Jitter the centroid by up to ~0.01 deg to spread points.
			Latitude:  c.lat + (r.Float64()-0.5)*0.02,
			Longitude: c.lng + (r.Float64()-0.5)*0.02,
			Media: []string{
				fmt.Sprintf("https://synthetic.local/%s/photo1.jpg", key),
				fmt.Sprintf("https://synthetic.local/%s/photo2.jpg", key),
			},
		})
	}
	return listings
}

// Validate reports whether a listing satisfies the RESO-shaped schema
// constraints the rest of the pipeline relies on. It returns an error
// describing the first violation, or nil when the listing is valid.
func (l Listing) Validate() error {
	switch {
	case l.ListingKey == "":
		return fmt.Errorf("ListingKey is required")
	case l.UnparsedAddress == "":
		return fmt.Errorf("UnparsedAddress is required")
	case l.City == "":
		return fmt.Errorf("City is required")
	case l.StateOrProvince == "":
		return fmt.Errorf("StateOrProvince is required")
	case len(l.PostalCode) != 5:
		return fmt.Errorf("PostalCode must be 5 digits, got %q", l.PostalCode)
	case l.BedroomsTotal <= 0:
		return fmt.Errorf("BedroomsTotal must be positive, got %d", l.BedroomsTotal)
	case l.BathroomsTotalInteger <= 0:
		return fmt.Errorf("BathroomsTotalInteger must be positive, got %d", l.BathroomsTotalInteger)
	case l.LivingArea <= 0:
		return fmt.Errorf("LivingArea must be positive, got %d", l.LivingArea)
	case l.ListPrice <= 0:
		return fmt.Errorf("ListPrice must be positive, got %d", l.ListPrice)
	case l.Latitude < 30.0 || l.Latitude > 30.6:
		return fmt.Errorf("Latitude %f outside Travis County bounds", l.Latitude)
	case l.Longitude < -98.2 || l.Longitude > -97.3:
		return fmt.Errorf("Longitude %f outside Travis County bounds", l.Longitude)
	case len(l.Media) == 0:
		return fmt.Errorf("at least one Media photo is required")
	}
	return nil
}
