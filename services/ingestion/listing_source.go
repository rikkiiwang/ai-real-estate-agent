package main

import (
	"context"
	"errors"
	"fmt"

	"github.com/airealestate/realestate/data/synthetic"
)

// ListingSource is the swappable source of normalized listing records. The MVP
// implementation generates synthetic RESO-shaped listings; a real Bridge/RESO
// feed implements the same interface later, so callers never change.
type ListingSource interface {
	// Listings returns normalized listing records, or an error. It honors
	// ctx cancellation/deadline.
	Listings(ctx context.Context) ([]ListingRecord, error)
}

// SyntheticListingSource is the MVP ListingSource. It produces deterministic,
// schema-valid Austin listings from the data/synthetic generator.
type SyntheticListingSource struct {
	Seed  int64
	Count int
}

// Listings generates and validates synthetic listings, normalizing them into
// ListingRecord. Invalid generated records are rejected with an error.
func (s SyntheticListingSource) Listings(ctx context.Context) ([]ListingRecord, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	gen := synthetic.Generate(s.Seed, s.Count)
	out := make([]ListingRecord, 0, len(gen))
	for _, l := range gen {
		if err := l.Validate(); err != nil {
			return nil, fmt.Errorf("synthetic listing %s invalid: %w", l.ListingKey, err)
		}
		out = append(out, ListingRecord{
			ListingKey: l.ListingKey,
			Address:    l.UnparsedAddress,
			City:       l.City,
			State:      l.StateOrProvince,
			PostalCode: l.PostalCode,
			Beds:       l.BedroomsTotal,
			Baths:      l.BathroomsTotalInteger,
			LivingArea: l.LivingArea,
			ListPrice:  l.ListPrice,
			Latitude:   l.Latitude,
			Longitude:  l.Longitude,
			Photos:     l.Media,
		})
	}
	return out, nil
}

// ErrNotImplemented is returned by stubs that are deferred to a later unit.
var ErrNotImplemented = errors.New("not implemented")

// BridgeRESOListingSource is a stub for the real ABoR/Unlock MLS RESO Web API
// feed (via Bridge). It is wired but returns ErrNotImplemented until the live
// feed is in scope. Holding the same interface as SyntheticListingSource lets
// callers swap it in without changes.
type BridgeRESOListingSource struct {
	BaseURL     string
	AccessToken string
}

// Listings is not implemented for the MVP; the synthetic source is used.
func (b BridgeRESOListingSource) Listings(ctx context.Context) ([]ListingRecord, error) {
	return nil, fmt.Errorf("BridgeRESOListingSource.Listings: %w", ErrNotImplemented)
}
