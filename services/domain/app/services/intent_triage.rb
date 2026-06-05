# Intent triaging (R5): looky-loo vs high-intent, from NEUTRAL signals only.
#
# Mirrors services/voice/qualify.go and the Fair-Housing equal-service guarantee
# (brain.lawyer.fair_housing): the triage reads only a fixed allow-list of
# neutral, transaction-relevant fields. Anything outside the allow-list — an
# inferred attribute or a protected-class proxy — is never consulted, so it can
# never change the outcome. This is the equal-service guarantee on the engagement
# side, enforced structurally rather than by convention.
class IntentTriage
  HIGH = "high_intent".freeze
  LOW = "low_intent_browser".freeze

  # The ONLY keys the qualifier may read, per side.
  NEUTRAL_SIGNALS = {
    "buyer"  => %w[preapproval move_timeline_days budget],
    "seller" => %w[address timeline motivation]
  }.freeze

  # A buyer counts as high-intent only with financing pre-approval AND a near-term
  # move (<= this many days). Demo-tuned heuristic, not a trained model.
  NEAR_TERM_DAYS = 30

  Result = Struct.new(:intent, :high_intent, :reason, :signals_used, keyword_init: true) do
    def high_intent? = high_intent
  end

  def self.call(signals:, side:)
    new(signals, side).call
  end

  def initialize(signals, side)
    @signals = (signals || {}).transform_keys(&:to_s)
    @side = side.to_s
  end

  def call
    allowed = NEUTRAL_SIGNALS.fetch(@side, [])
    used = allowed.select { |k| present?(k) }

    high, reason = @side == "seller" ? seller_intent(used) : buyer_intent(used)

    Result.new(
      intent: high ? HIGH : LOW,
      high_intent: high,
      reason: reason,
      signals_used: used
    )
  end

  private

  # Buyer: pre-approval AND a stated move within NEAR_TERM_DAYS.
  def buyer_intent(_used)
    preapproved = truthy?("preapproval")
    days = @signals["move_timeline_days"].to_s.strip
    near_term = !days.empty? && days.to_i.positive? && days.to_i <= NEAR_TERM_DAYS

    if preapproved && near_term
      [true, "pre-approved for financing and moving within #{NEAR_TERM_DAYS} days"]
    elsif preapproved
      [false, "pre-approved, but no near-term move timeline (need a move within #{NEAR_TERM_DAYS} days)"]
    elsif near_term
      [false, "near-term move, but not yet financing pre-approved"]
    else
      [false, "browsing — no financing pre-approval or near-term move timeline yet"]
    end
  end

  # Seller: an address plus a stated timeline or motivation to sell.
  def seller_intent(_used)
    has_address = present?("address")
    has_signal = present?("timeline") || present?("motivation")

    if has_address && has_signal
      [true, "address plus a stated timeline/motivation to sell"]
    else
      [false, "insufficient neutral signals: need an address and a timeline/motivation to sell"]
    end
  end

  def present?(key)
    !@signals[key].to_s.strip.empty?
  end

  def truthy?(key)
    %w[true 1 yes y t].include?(@signals[key].to_s.strip.downcase)
  end
end
