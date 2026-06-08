package main

import "testing"

type fakeRelay struct{ got string }

func (f *fakeRelay) Reply(contact, text string) (string, error) {
	f.got = text
	return "spoken reply", nil
}

func TestHandleMessageAppendsRelayReply(t *testing.T) {
	relay := &fakeRelay{}
	srv := &server{manager: NewManager(), relay: relay}
	sess := srv.manager.Start()
	srv.manager.AppendTurn(sess.ID, RoleSeller, "hello", nil)

	reply, ok := srv.relayReply(sess.ID, "what's my home worth?")
	if !ok || reply != "spoken reply" {
		t.Fatalf("expected relay reply, got %q ok=%v", reply, ok)
	}
	if relay.got != "what's my home worth?" {
		t.Fatalf("relay saw %q", relay.got)
	}
	got, _ := srv.manager.Get(sess.ID)
	last := got.Thread[len(got.Thread)-1]
	if last.Role != RoleAgent || last.Text != "spoken reply" {
		t.Fatalf("agent turn not appended: %+v", last)
	}
}

func TestRelayReplyNoRelayIsNoop(t *testing.T) {
	srv := &server{manager: NewManager()}
	sess := srv.manager.Start()
	if _, ok := srv.relayReply(sess.ID, "hi"); ok {
		t.Fatalf("expected no relay -> ok=false")
	}
}
