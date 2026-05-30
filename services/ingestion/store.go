package main

import "sync"

// SourceStore is the in-memory sink ingestion emits normalized records into.
// Real pgvector persistence is U5's job; this interface keeps U2 decoupled from
// it. The store is keyed by ParcelID for properties and ListingKey for
// listings.
type SourceStore interface {
	PutProperty(rec PropertyRecord)
	PutListing(rec ListingRecord)
	Properties() []PropertyRecord
	Listings() []ListingRecord
}

// MemStore is a goroutine-safe in-memory SourceStore.
type MemStore struct {
	mu         sync.RWMutex
	properties map[string]PropertyRecord
	listings   map[string]ListingRecord
}

// NewMemStore returns an empty in-memory store.
func NewMemStore() *MemStore {
	return &MemStore{
		properties: make(map[string]PropertyRecord),
		listings:   make(map[string]ListingRecord),
	}
}

// PutProperty inserts or replaces a property record by ParcelID.
func (s *MemStore) PutProperty(rec PropertyRecord) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.properties[rec.ParcelID] = rec
}

// PutListing inserts or replaces a listing record by ListingKey.
func (s *MemStore) PutListing(rec ListingRecord) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.listings[rec.ListingKey] = rec
}

// Properties returns a snapshot of stored property records.
func (s *MemStore) Properties() []PropertyRecord {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]PropertyRecord, 0, len(s.properties))
	for _, r := range s.properties {
		out = append(out, r)
	}
	return out
}

// Listings returns a snapshot of stored listing records.
func (s *MemStore) Listings() []ListingRecord {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]ListingRecord, 0, len(s.listings))
	for _, r := range s.listings {
		out = append(out, r)
	}
	return out
}
