package synthetic

import "testing"

// Generated listings validate against the RESO-shaped schema.
func TestGenerateValidates(t *testing.T) {
	listings := Generate(99, 100)
	if len(listings) != 100 {
		t.Fatalf("want 100, got %d", len(listings))
	}
	for _, l := range listings {
		if err := l.Validate(); err != nil {
			t.Errorf("generated listing invalid: %v (%+v)", err, l)
		}
	}
}

// Same seed yields identical output.
func TestGenerateDeterministic(t *testing.T) {
	a := Generate(5, 20)
	b := Generate(5, 20)
	for i := range a {
		if a[i].ListingKey != b[i].ListingKey || a[i].ListPrice != b[i].ListPrice ||
			a[i].Latitude != b[i].Latitude || a[i].UnparsedAddress != b[i].UnparsedAddress {
			t.Fatalf("not deterministic at %d", i)
		}
	}
}

// Validate rejects out-of-schema records.
func TestValidateRejects(t *testing.T) {
	good := Generate(1, 1)[0]

	bad := good
	bad.PostalCode = "ABC"
	if bad.Validate() == nil {
		t.Error("expected bad postal code to fail")
	}

	bad = good
	bad.BedroomsTotal = 0
	if bad.Validate() == nil {
		t.Error("expected zero beds to fail")
	}

	bad = good
	bad.Media = nil
	if bad.Validate() == nil {
		t.Error("expected missing media to fail")
	}

	bad = good
	bad.Latitude = 40.0
	if bad.Validate() == nil {
		t.Error("expected out-of-county latitude to fail")
	}
}
