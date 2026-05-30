package main

import (
	"context"
	"io"
)

// IngestProperties parses GIS + TCAD fixtures (or live readers), joins them,
// and writes the resulting normalized PropertyRecords into the store. It
// returns the number of records emitted. Readers let callers feed live HTTP
// bodies, files, or recorded test fixtures interchangeably — no network is
// assumed.
func IngestProperties(store SourceStore, gis, tcad io.Reader) (int, error) {
	parcels, err := ParseGISParcels(gis)
	if err != nil {
		return 0, err
	}
	records, err := ParseTCADRecords(tcad)
	if err != nil {
		return 0, err
	}
	joined := JoinGISAndTCAD(parcels, records)
	for _, rec := range joined {
		store.PutProperty(rec)
	}
	return len(joined), nil
}

// IngestListings pulls normalized listings from the given ListingSource and
// writes them into the store. Swapping the ListingSource implementation
// (synthetic vs. Bridge/RESO) requires no change here.
func IngestListings(ctx context.Context, store SourceStore, src ListingSource) (int, error) {
	listings, err := src.Listings(ctx)
	if err != nil {
		return 0, err
	}
	for _, l := range listings {
		store.PutListing(l)
	}
	return len(listings), nil
}
