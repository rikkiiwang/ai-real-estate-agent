package main

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

// --- Synthetic listings validate against the RESO-shaped schema ---

func TestSyntheticListingsValidate(t *testing.T) {
	src := SyntheticListingSource{Seed: 42, Count: 25}
	listings, err := src.Listings(context.Background())
	if err != nil {
		t.Fatalf("Listings: %v", err)
	}
	if len(listings) != 25 {
		t.Fatalf("want 25 listings, got %d", len(listings))
	}
	for _, l := range listings {
		if l.ListingKey == "" || l.Address == "" || l.City != "Austin" {
			t.Errorf("listing failed basic shape: %+v", l)
		}
		if l.Beds <= 0 || l.Baths <= 0 || l.LivingArea <= 0 || l.ListPrice <= 0 {
			t.Errorf("listing has non-positive numeric field: %+v", l)
		}
		if len(l.PostalCode) != 5 {
			t.Errorf("bad postal code %q", l.PostalCode)
		}
		if len(l.Photos) == 0 {
			t.Errorf("listing %s has no photos", l.ListingKey)
		}
		if l.Latitude < 30.0 || l.Latitude > 30.6 || l.Longitude < -98.2 || l.Longitude > -97.3 {
			t.Errorf("listing coords outside Travis County: %+v", l)
		}
	}
}

// Generation is deterministic for a given seed.
func TestSyntheticDeterministic(t *testing.T) {
	a, _ := SyntheticListingSource{Seed: 7, Count: 10}.Listings(context.Background())
	b, _ := SyntheticListingSource{Seed: 7, Count: 10}.Listings(context.Background())
	if len(a) != len(b) {
		t.Fatalf("length mismatch")
	}
	for i := range a {
		if !equalListing(a[i], b[i]) {
			t.Errorf("seed not deterministic at %d: %+v vs %+v", i, a[i], b[i])
		}
	}
}

func equalListing(a, b ListingRecord) bool {
	if a.ListingKey != b.ListingKey || a.Address != b.Address || a.ListPrice != b.ListPrice ||
		a.Beds != b.Beds || a.Baths != b.Baths || a.LivingArea != b.LivingArea ||
		a.Latitude != b.Latitude || a.Longitude != b.Longitude {
		return false
	}
	if len(a.Photos) != len(b.Photos) {
		return false
	}
	for i := range a.Photos {
		if a.Photos[i] != b.Photos[i] {
			return false
		}
	}
	return true
}

// --- GIS + TCAD join on a known parcel from fixtures ---

func TestJoinKnownParcel(t *testing.T) {
	gisF := mustOpen(t, "testdata/gis_parcels.json")
	defer gisF.Close()
	tcadF := mustOpen(t, "testdata/tcad_records.json")
	defer tcadF.Close()

	store := NewMemStore()
	n, err := IngestProperties(store, gisF, tcadF)
	if err != nil {
		t.Fatalf("IngestProperties: %v", err)
	}
	if n == 0 {
		t.Fatal("no records emitted")
	}

	var joined *PropertyRecord
	for _, p := range store.Properties() {
		if p.ParcelID == "123456" {
			pp := p
			joined = &pp
		}
	}
	if joined == nil {
		t.Fatal("known parcel 123456 not found in store")
	}
	if joined.AppraisedValue != 625000 {
		t.Errorf("want appraised 625000, got %d", joined.AppraisedValue)
	}
	if joined.LivingArea != 2150 || joined.YearBuilt != 1998 {
		t.Errorf("TCAD fields not joined: %+v", joined)
	}
	if joined.Latitude != 30.2747 || joined.Longitude != -97.7404 {
		t.Errorf("GIS geometry not joined: %+v", joined)
	}
	if !contains(joined.Sources, "gis_attribute") || !contains(joined.Sources, "tcad_appraisal") {
		t.Errorf("expected both sources, got %v", joined.Sources)
	}
}

// Numeric parcel id in GIS attributes is coerced and still joins.
func TestNumericParcelIDJoins(t *testing.T) {
	gis := strings.NewReader(`{"features":[{"attributes":{"PROP_ID":789012,"SITUS":"x"},"geometry":{"x":-97.74,"y":30.28}}]}`)
	tcad := strings.NewReader(`[{"account_number":"789012","appraised_value":"400000"}]`)
	store := NewMemStore()
	if _, err := IngestProperties(store, gis, tcad); err != nil {
		t.Fatalf("ingest: %v", err)
	}
	props := store.Properties()
	if len(props) != 1 || props[0].AppraisedValue != 400000 {
		t.Fatalf("numeric parcel id did not join: %+v", props)
	}
}

// --- Missing / partial / malformed records ---

func TestPartialAndMalformedRecordsSkipped(t *testing.T) {
	gisF := mustOpen(t, "testdata/gis_parcels.json")
	defer gisF.Close()
	tcadF := mustOpen(t, "testdata/tcad_records.json")
	defer tcadF.Close()

	parcels, err := ParseGISParcels(gisF)
	if err != nil {
		t.Fatalf("ParseGISParcels: %v", err)
	}
	// 3 features but one has no parcel id -> 2 parcels.
	if len(parcels) != 2 {
		t.Errorf("want 2 parcels (1 skipped), got %d", len(parcels))
	}
	records, err := ParseTCADRecords(tcadF)
	if err != nil {
		t.Fatalf("ParseTCADRecords: %v", err)
	}
	// 3 records but one has no account -> 2 records.
	if len(records) != 2 {
		t.Errorf("want 2 TCAD records (1 skipped), got %d", len(records))
	}

	// TCAD-only record (555000) is still emitted, geometry-less.
	joined := JoinGISAndTCAD(parcels, records)
	var tcadOnly *PropertyRecord
	for i := range joined {
		if joined[i].ParcelID == "555000" {
			tcadOnly = &joined[i]
		}
	}
	if tcadOnly == nil {
		t.Fatal("TCAD-only record dropped")
	}
	if tcadOnly.Latitude != 0 || tcadOnly.Longitude != 0 {
		t.Errorf("TCAD-only record should have no geometry: %+v", tcadOnly)
	}
}

func TestMalformedGISJSON(t *testing.T) {
	_, err := ParseGISParcels(strings.NewReader(`{not valid json`))
	if err == nil {
		t.Fatal("expected error on malformed GIS JSON")
	}
}

func TestGISServiceError(t *testing.T) {
	f := mustOpen(t, "testdata/gis_error.json")
	defer f.Close()
	_, err := ParseGISParcels(f)
	if err == nil || !strings.Contains(err.Error(), "GIS service error") {
		t.Fatalf("expected GIS service error, got %v", err)
	}
}

// --- Upstream timeout/error handled without crashing ---

func TestFetchGISTimeout(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(200 * time.Millisecond)
		_, _ = w.Write([]byte(`{"features":[]}`))
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()

	_, err := FetchGISParcels(ctx, srv.Client(), srv.URL)
	if err == nil {
		t.Fatal("expected timeout error, got nil")
	}
	// Crucially, the call returned an error instead of panicking.
}

func TestFetchGISBadStatus(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()
	_, err := FetchGISParcels(context.Background(), srv.Client(), srv.URL)
	if err == nil {
		t.Fatal("expected error on 500 status")
	}
}

func TestFetchGISHappyPath(t *testing.T) {
	body := `{"features":[{"attributes":{"PROP_ID":"42","SITUS":"a"},"geometry":{"x":-97.74,"y":30.27}}]}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()
	parcels, err := FetchGISParcels(context.Background(), srv.Client(), srv.URL)
	if err != nil {
		t.Fatalf("FetchGISParcels: %v", err)
	}
	if len(parcels) != 1 || parcels[0].ParcelID != "42" {
		t.Fatalf("unexpected parcels: %+v", parcels)
	}
}

// --- Swapping ListingSource impls needs no caller change ---

func TestListingSourceSwappable(t *testing.T) {
	store := NewMemStore()

	// Caller uses the interface, not the concrete type.
	var src ListingSource = SyntheticListingSource{Seed: 1, Count: 5}
	n, err := IngestListings(context.Background(), store, src)
	if err != nil {
		t.Fatalf("synthetic ingest: %v", err)
	}
	if n != 5 || len(store.Listings()) != 5 {
		t.Fatalf("expected 5 listings, got n=%d store=%d", n, len(store.Listings()))
	}

	// Swap to the Bridge/RESO stub via the SAME call site.
	src = BridgeRESOListingSource{BaseURL: "https://api.bridgedataoutput.com"}
	_, err = IngestListings(context.Background(), store, src)
	if !errors.Is(err, ErrNotImplemented) {
		t.Fatalf("expected ErrNotImplemented from Bridge stub, got %v", err)
	}
}

// --- helpers ---

func mustOpen(t *testing.T, path string) *os.File {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("open %s: %v", path, err)
	}
	return f
}

func contains(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}
