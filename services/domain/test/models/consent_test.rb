require "test_helper"

class ConsentTest < ActiveSupport::TestCase
  setup do
    @lead = Lead.create!(side: "seller", address: "123 Main St, Austin", intent: "high")
  end

  test "opted-in lead with no opt-out and no DNC is contactable" do
    consent = @lead.consents.create!(channel: "voice", opted_in: true)
    assert consent.contactable?
    assert Consent.outreach_allowed?(lead: @lead, channel: "voice")
  end

  test "non-consented (not opted-in) contact is blocked" do
    consent = @lead.consents.create!(channel: "sms", opted_in: false)
    assert_not consent.contactable?
    assert_not Consent.outreach_allowed?(lead: @lead, channel: "sms")
  end

  test "opt-out immediately suppresses further outreach" do
    consent = @lead.consents.create!(channel: "voice", opted_in: true)
    assert Consent.outreach_allowed?(lead: @lead, channel: "voice")

    consent.opt_out!

    assert consent.opted_out?
    assert_not consent.contactable?
    assert_not Consent.outreach_allowed?(lead: @lead, channel: "voice")
    # A fresh reload from the DB must also be suppressed (persisted, not just
    # an in-memory flip).
    assert_not Consent.find(consent.id).contactable?
  end

  test "DNC blocks outreach even when opted in" do
    consent = @lead.consents.create!(channel: "sms", opted_in: true, dnc: true)
    assert_not consent.contactable?
    assert_not Consent.outreach_allowed?(lead: @lead, channel: "sms")
  end

  test "fail-closed when no consent record exists for the channel" do
    # An opted-in voice consent must not authorize sms outreach.
    @lead.consents.create!(channel: "voice", opted_in: true)
    assert_not Consent.outreach_allowed?(lead: @lead, channel: "sms")
    # And a lead with no consent at all is never contactable.
    bare = Lead.create!(side: "buyer", address: "9 Elm")
    assert_not Consent.outreach_allowed?(lead: bare, channel: "voice")
  end

  test "channel must be valid" do
    consent = @lead.consents.build(channel: "carrier_pigeon", opted_in: true)
    assert_not consent.valid?
    assert_includes consent.errors[:channel], "is not included in the list"
  end

  test "one consent per lead and channel" do
    @lead.consents.create!(channel: "voice", opted_in: true)
    dup = @lead.consents.build(channel: "voice", opted_in: false)
    assert_not dup.valid?
  end

  test "belongs to a lead" do
    consent = Consent.new(channel: "voice", opted_in: true)
    assert_not consent.valid?
    assert_includes consent.errors[:lead], "must exist"
  end
end
