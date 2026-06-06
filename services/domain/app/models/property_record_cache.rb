class PropertyRecordCache < ApplicationRecord
  validates :address, presence: true, uniqueness: { case_sensitive: false }

  # Stale after this TTL; the prewarm task refreshes only past-TTL rows.
  TTL = 14.days
  scope :fresh, -> { where("captured_at >= ?", TTL.ago) }
  def fresh? = captured_at.present? && captured_at >= TTL.ago
end
