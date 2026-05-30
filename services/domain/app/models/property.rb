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

  validates :address, presence: true
  validates :state, presence: true, inclusion: { in: STATES }

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
