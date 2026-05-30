class Negotiation < ApplicationRecord
  belongs_to :offer

  validates :counter_amount, numericality: { greater_than: 0 }
  validates :band_low, :band_high, presence: true
  validate :band_well_formed

  # Records a counter and stamps whether it sits within the authorized band.
  # Counters outside the band are recorded (not discarded) so an out-of-band
  # move can route to a human broker (handoff) rather than auto-negotiate.
  before_validation :stamp_within_band

  def within_band?
    return false if band_low.nil? || band_high.nil? || counter_amount.nil?

    counter_amount >= band_low && counter_amount <= band_high
  end

  private

  def stamp_within_band
    self.within_band = within_band?
  end

  def band_well_formed
    return if band_low.nil? || band_high.nil?

    errors.add(:band_high, "must be >= band_low") if band_high < band_low
  end
end
