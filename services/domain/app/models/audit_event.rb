require "digest"

# APPEND-ONLY audit log for claim->source decisions (the Critic/Lawyer) and
# rail trips (Fair Housing, confidence/HITL).
#
# Append-only is enforced HERE, at the model layer: any attempt to update or
# destroy a persisted row raises. A lightweight per-row hash chain
# (prev_hash -> content_hash) makes after-the-fact tampering detectable.
#
# NOTE (flagged in review): true DB-level tamper-evidence — a hash chain
# validated inside the database plus REVOKE of UPDATE/DELETE from the
# application's DB role — is a follow-up. The enforced guarantee in this unit
# is model-layer append-only + the per-row hash chain, covered by tests.
class AuditEvent < ApplicationRecord
  # Common kinds, kept open (string) so new rail trips don't need a migration.
  KINDS = %w[claim_source_decision fair_housing_trip confidence_handoff].freeze

  validates :kind, presence: true

  before_create :chain_hashes
  before_update { raise ActiveRecord::ReadOnlyRecord, "AuditEvent is append-only" }
  before_destroy { raise ActiveRecord::ReadOnlyRecord, "AuditEvent is append-only" }

  # Record a Critic claim->source verification decision.
  def self.record_claim_decision(claim:, source_id:, decision:, subject: nil, detail: nil)
    log(kind: "claim_source_decision", claim: claim, source_id: source_id,
        decision: decision, subject: subject, detail: detail)
  end

  # Record a rail trip (Fair Housing, confidence handoff, etc.).
  def self.record_rail_trip(kind:, decision:, subject: nil, detail: nil)
    log(kind: kind, decision: decision, subject: subject, detail: detail)
  end

  def self.log(subject: nil, **attrs)
    if subject
      attrs[:subject_type] = subject.class.name
      attrs[:subject_id] = subject.id.to_s
    end
    create!(**attrs)
  end

  # Recompute each row's content hash and confirm the prev_hash chain is
  # intact end-to-end. Returns true when the log has not been tampered with.
  def self.chain_intact?
    prev = nil
    order(:id).each do |event|
      return false if event.prev_hash != prev
      return false if event.content_hash != event.compute_content_hash

      prev = event.content_hash
    end
    true
  end

  def compute_content_hash
    payload = [ kind, subject_type, subject_id, claim, source_id, decision, detail, prev_hash ].join("|")
    Digest::SHA256.hexdigest(payload)
  end

  private

  def chain_hashes
    self.prev_hash = self.class.order(:id).last&.content_hash
    self.content_hash = compute_content_hash
  end
end
