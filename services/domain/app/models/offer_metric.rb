class OfferMetric < ApplicationRecord
  belongs_to :offer
  belongs_to :lead

  validates :side, presence: true, inclusion: { in: Offer::SIDES }
  validates :seconds_to_offer, numericality: { greater_than_or_equal_to: 0 }
  validates :recorded_at, presence: true

  # Record the time-to-offer for a freshly drafted offer: the elapsed seconds
  # between the lead being created and the offer being drafted. Idempotent per
  # offer so re-drafting (or replaying the queue step) never double-counts.
  def self.record_for(offer, recorded_at: Time.current)
    lead = offer.lead
    find_or_create_by!(offer: offer) do |metric|
      metric.lead = lead
      metric.side = offer.side
      metric.seconds_to_offer = (recorded_at - lead.created_at).round
      metric.recorded_at = recorded_at
    end
  end

  # Aggregate time-to-offer per side and overall, for the broker dashboard.
  def self.summary
    grouped = all.group_by(&:side)
    sides = Offer::SIDES.index_with { |side| stats_for(grouped.fetch(side, [])) }
    sides.merge("all" => stats_for(all.to_a))
  end

  def self.stats_for(metrics)
    count = metrics.size
    return { count: 0, average_seconds: nil } if count.zero?

    average = metrics.sum(&:seconds_to_offer).fdiv(count).round
    { count: count, average_seconds: average }
  end
end
