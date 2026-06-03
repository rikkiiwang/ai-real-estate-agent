class Property < ApplicationRecord
  # Lifecycle: acquired -> listed -> under_offer -> sold (forward-only).
  STATES = %w[acquired listed under_offer sold].freeze

  # Allowed forward transitions. Anything not listed here is illegal and
  # raises (e.g. you cannot list a property before it is acquired).
  TRANSITIONS = {
    "acquired"    => %w[listed],
    "listed"      => %w[under_offer],
    "under_offer" => %w[sold listed],
    "sold"        => []
  }.freeze

  has_many :offers, dependent: :nullify
  has_many :comps, dependent: :nullify

  validates :address, presence: true
  validates :state, presence: true, inclusion: { in: STATES }
  validates :list_price, numericality: { greater_than: 0 }, allow_nil: true

  # Listings a consumer can browse and offer on: listed state with a real
  # asking price (the internal acquire->list lifecycle may have no price yet).
  scope :listed, -> { where(state: "listed") }
  scope :browsable, -> { listed.where.not(list_price: nil) }
  scope :in_region, ->(region) { region.present? ? where(region: region) : all }
  scope :priced_between, lambda { |min, max|
    rel = all
    rel = rel.where("list_price >= ?", min) if min.present?
    rel = rel.where("list_price <= ?", max) if max.present?
    rel
  }
  scope :min_beds, ->(beds) { beds.present? ? where("beds >= ?", beds) : all }

  class IllegalTransition < StandardError; end

  def list!  = transition_to!("listed")
  def mark_under_offer! = transition_to!("under_offer")
  def sell!  = transition_to!("sold")

  # Guarded lifecycle move. Raises IllegalTransition on an illegal jump so a
  # property can never skip or reverse its lifecycle silently.
  def transition_to!(next_state)
    unless TRANSITIONS.fetch(state, []).include?(next_state)
      raise IllegalTransition, "cannot move property from #{state.inspect} to #{next_state.inspect}"
    end

    update!(state: next_state)
  end
end
