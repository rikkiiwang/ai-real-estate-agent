# One met closing milestone on a signed deal (R10). Records which counterparty
# was pinged and whether the ping was emitted by the brain orchestrator
# ("simulated") or queued locally because the brain was unreachable ("pending").
class ClosingMilestone < ApplicationRecord
  MILESTONES = %w[inspection_cleared earnest_deposited title_cleared funded].freeze
  PING_STATUSES = %w[simulated pending].freeze
  COUNTERPARTY_LABEL = { "escrow" => "Escrow officer", "title" => "Title company", "lender" => "Lender" }.freeze

  belongs_to :offer

  validates :milestone, inclusion: { in: MILESTONES }, uniqueness: { scope: :offer_id }
  validates :ping_status, inclusion: { in: PING_STATUSES }

  def counterparty_label = COUNTERPARTY_LABEL[counterparty] || counterparty
end
