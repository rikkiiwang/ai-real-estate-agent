package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// GISParcel is a normalized Travis County GIS parcel: geometry centroid plus
// the attributes ingestion needs to join to TCAD and emit a PropertyRecord.
type GISParcel struct {
	ParcelID  string
	Address   string
	Latitude  float64
	Longitude float64
}

// arcGISResponse models the subset of an ArcGIS GeoServices query response
// (f=json) that ingestion consumes. Each feature carries flat attributes and a
// point geometry (x=longitude, y=latitude).
type arcGISResponse struct {
	Error    *arcGISError    `json:"error"`
	Features []arcGISFeature `json:"features"`
}

type arcGISError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type arcGISFeature struct {
	Attributes map[string]any `json:"attributes"`
	Geometry   *arcGISGeom    `json:"geometry"`
}

type arcGISGeom struct {
	X float64 `json:"x"` // longitude
	Y float64 `json:"y"` // latitude
}

// ParseGISParcels parses an ArcGIS GeoServices query response from r into
// normalized parcels. The parcel id is read from PROP_ID/PROPERTY_ID/PARCEL_ID
// (Travis County / TCAD account number) and the address from SITUS/ADDRESS.
// Features missing a parcel id are skipped. A service-level error in the
// payload is surfaced as an error.
func ParseGISParcels(r io.Reader) ([]GISParcel, error) {
	var resp arcGISResponse
	if err := json.NewDecoder(r).Decode(&resp); err != nil {
		return nil, fmt.Errorf("decode GIS response: %w", err)
	}
	if resp.Error != nil {
		return nil, fmt.Errorf("GIS service error %d: %s", resp.Error.Code, resp.Error.Message)
	}
	parcels := make([]GISParcel, 0, len(resp.Features))
	for _, f := range resp.Features {
		id := firstString(f.Attributes, "PROP_ID", "PROPERTY_ID", "PARCEL_ID", "GEO_ID")
		if id == "" {
			// Malformed/partial feature with no parcel key: skip, do not crash.
			continue
		}
		p := GISParcel{
			ParcelID: id,
			Address:  firstString(f.Attributes, "SITUS", "SITUS_ADDRESS", "ADDRESS"),
		}
		if f.Geometry != nil {
			p.Latitude = f.Geometry.Y
			p.Longitude = f.Geometry.X
		}
		parcels = append(parcels, p)
	}
	return parcels, nil
}

// firstString returns the first attribute among keys that holds a non-empty
// string (numbers are coerced to string). ArcGIS attribute values are loosely
// typed, so account numbers may arrive as strings or numbers.
func firstString(attrs map[string]any, keys ...string) string {
	for _, k := range keys {
		v, ok := attrs[k]
		if !ok {
			continue
		}
		switch t := v.(type) {
		case string:
			if t != "" {
				return t
			}
		case float64:
			// Account numbers come through JSON as float64; render without
			// scientific notation or trailing decimals.
			return fmt.Sprintf("%.0f", t)
		case json.Number:
			return t.String()
		}
	}
	return ""
}

// FetchGISParcels queries a live ArcGIS GeoServices endpoint and parses the
// result. The http.Client is injected so tests can supply a recorded fixture
// transport and never hit the network. ctx bounds the request; an upstream
// timeout or transport error is returned, not panicked.
func FetchGISParcels(ctx context.Context, client *http.Client, queryURL string) ([]GISParcel, error) {
	if client == nil {
		client = http.DefaultClient
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, queryURL, nil)
	if err != nil {
		return nil, fmt.Errorf("build GIS request: %w", err)
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("GIS request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GIS request returned status %d", resp.StatusCode)
	}
	return ParseGISParcels(resp.Body)
}
