package main

import (
	"encoding/json"
	"fmt"
	"io"
)

// TCADRecord is a normalized TCAD appraisal record obtained via Public
// Information Request bulk export, keyed on the property (account) number that
// joins to a GIS parcel.
type TCADRecord struct {
	AccountNumber    string
	LandValue        int
	ImprovementValue int
	AppraisedValue   int
	YearBuilt        int
	LivingArea       int // square feet
}

// tcadRaw models the documented TCAD bulk record JSON. Numeric fields arrive as
// strings in the PIR export, so they are parsed leniently.
type tcadRaw struct {
	PropertyNumber   string `json:"property_number"`
	AccountNumber    string `json:"account_number"`
	LandValue        any    `json:"land_value"`
	ImprovementValue any    `json:"improvement_value"`
	AppraisedValue   any    `json:"appraised_value"`
	YearBuilt        any    `json:"year_built"`
	LivingArea       any    `json:"living_area"`
}

// ParseTCADRecords parses a TCAD bulk export (a JSON array of records) from r.
// Records missing an account/property number are skipped rather than crashing
// the loader. Malformed numeric fields default to zero.
func ParseTCADRecords(r io.Reader) ([]TCADRecord, error) {
	var raw []tcadRaw
	if err := json.NewDecoder(r).Decode(&raw); err != nil {
		return nil, fmt.Errorf("decode TCAD export: %w", err)
	}
	out := make([]TCADRecord, 0, len(raw))
	for _, rec := range raw {
		acct := rec.AccountNumber
		if acct == "" {
			acct = rec.PropertyNumber
		}
		if acct == "" {
			// Partial record with no join key: skip.
			continue
		}
		out = append(out, TCADRecord{
			AccountNumber:    acct,
			LandValue:        toInt(rec.LandValue),
			ImprovementValue: toInt(rec.ImprovementValue),
			AppraisedValue:   toInt(rec.AppraisedValue),
			YearBuilt:        toInt(rec.YearBuilt),
			LivingArea:       toInt(rec.LivingArea),
		})
	}
	return out, nil
}

// toInt coerces a loosely-typed JSON value (string or number) to an int,
// returning 0 for empty/unparseable values.
func toInt(v any) int {
	switch t := v.(type) {
	case float64:
		return int(t)
	case json.Number:
		n, _ := t.Int64()
		return int(n)
	case string:
		var n int
		// Tolerate currency/grouping noise by scanning leading digits.
		for _, c := range t {
			if c < '0' || c > '9' {
				if n != 0 {
					break
				}
				continue
			}
			n = n*10 + int(c-'0')
		}
		return n
	}
	return 0
}

// JoinGISAndTCAD joins GIS parcels to TCAD records on parcel/account number and
// emits normalized PropertyRecords. Parcels without a matching TCAD record are
// still emitted (geometry-only), and vice-versa: a TCAD record without a parcel
// is emitted with no geometry. This makes the join total so partial coverage on
// either side does not drop a property silently.
func JoinGISAndTCAD(parcels []GISParcel, records []TCADRecord) []PropertyRecord {
	byAcct := make(map[string]TCADRecord, len(records))
	for _, r := range records {
		byAcct[r.AccountNumber] = r
	}
	matched := make(map[string]bool)
	out := make([]PropertyRecord, 0, len(parcels))

	for _, p := range parcels {
		rec := PropertyRecord{
			ParcelID:  p.ParcelID,
			Address:   p.Address,
			Latitude:  p.Latitude,
			Longitude: p.Longitude,
			Sources:   []string{"gis_attribute"},
		}
		if t, ok := byAcct[p.ParcelID]; ok {
			rec.LandValue = t.LandValue
			rec.ImprovementValue = t.ImprovementValue
			rec.AppraisedValue = t.AppraisedValue
			rec.YearBuilt = t.YearBuilt
			rec.LivingArea = t.LivingArea
			rec.Sources = append(rec.Sources, "tcad_appraisal")
			matched[p.ParcelID] = true
		}
		out = append(out, rec)
	}

	// TCAD records with no GIS parcel: emit geometry-less, so appraisal data is
	// not lost when GIS coverage lags the PIR export.
	for _, t := range records {
		if matched[t.AccountNumber] {
			continue
		}
		out = append(out, PropertyRecord{
			ParcelID:         t.AccountNumber,
			LandValue:        t.LandValue,
			ImprovementValue: t.ImprovementValue,
			AppraisedValue:   t.AppraisedValue,
			YearBuilt:        t.YearBuilt,
			LivingArea:       t.LivingArea,
			Sources:          []string{"tcad_appraisal"},
		})
	}
	return out
}
