# Cached vision analysis for a listing (R2): a photo-derived condition score plus
# structured, image-cited findings. Written off the request path by the capped
# `rake vision:analyze` task (or labeled sample seeds); read by the valuation and
# the "What the photos show" UI. `findings` are buyer-safe value-features;
# `needs_review` (red-flags / low-confidence) is broker-only — never shown to buyers.
class PhotoAnalysis < ApplicationRecord
  belongs_to :property, optional: true

  validates :address, presence: true, uniqueness: { case_sensitive: false }

  # Stale after this TTL; the analyze task refreshes only past-TTL rows.
  TTL = 30.days
  scope :fresh, -> { where("analyzed_at >= ?", TTL.ago) }

  def fresh? = analyzed_at.present? && analyzed_at >= TTL.ago

  # Arrays of {"kind","label","confidence","evidence_photo_id"} hashes (JSON column).
  def feature_findings = Array(findings)
  def review_findings = Array(needs_review)

  def from_claude? = provenance.to_s.start_with?("claude")
end
