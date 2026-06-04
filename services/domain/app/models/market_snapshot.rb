class MarketSnapshot < ApplicationRecord
  # A cached, dated snapshot of real Austin sale-market stats (from RentCast),
  # so the marketplace can show genuine "market intelligence" without calling the
  # rate-limited feed on every request.
  validates :area, presence: true
  validates :source, presence: true

  scope :recent_first, -> { order(as_of: :desc, updated_at: :desc) }

  # The headline snapshot to show on the catalog (most recently refreshed).
  def self.headline
    recent_first.first
  end
end
