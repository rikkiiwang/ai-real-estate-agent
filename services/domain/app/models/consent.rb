class Consent < ApplicationRecord
  CHANNELS = %w[voice sms chat email].freeze

  belongs_to :lead

  validates :channel, presence: true, inclusion: { in: CHANNELS }
  validates :lead_id, uniqueness: { scope: :channel }

  # The outreach gate (R10, consent-first). Contact is permitted ONLY when the
  # consumer has affirmatively opted in, has not opted out, and is not on the
  # Do-Not-Contact list. Any other state — including no resolvable consent
  # record at all — means NO outreach (fail-closed).
  def contactable?
    opted_in? && !opted_out? && !dnc?
  end

  # Opt-out is immediate and irreversible within this record: it stamps the
  # opt-out time and drops opted_in, so the very next contactable? check (and
  # any reload of this consent) suppresses further outreach.
  def opt_out!
    update!(opted_out_at: Time.current, opted_in: false)
  end

  def opted_out?
    opted_out_at.present?
  end

  # The fail-closed entry point for a contact attempt. Resolves the consent for
  # (lead, channel) and returns true ONLY if a record exists AND it is
  # contactable. A missing consent record (no resolvable consent) returns false:
  # silence is never consent.
  def self.outreach_allowed?(lead:, channel:)
    find_by(lead: lead, channel: channel)&.contactable? || false
  end
end
