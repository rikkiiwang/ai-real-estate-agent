class Visitor < ApplicationRecord
  # A lightweight consumer identity — name + email, no password. One identity
  # owns both the Buyer and Seller workspaces (they are parallel contexts, not
  # mutually exclusive roles).
  validates :name, presence: true
  validates :email, presence: true,
                    uniqueness: { case_sensitive: false },
                    format: { with: URI::MailTo::EMAIL_REGEXP }

  normalizes :email, with: ->(e) { e.to_s.strip.downcase }

  # Find an existing visitor by email or create one. Lets a returning visitor
  # sign back in without a password and keep their identity.
  def self.sign_in(name:, email:)
    visitor = find_or_initialize_by(email: email.to_s.strip.downcase)
    visitor.name = name if name.present?
    visitor.save
    visitor
  end

  # A broker is a normal signed-in visitor whose email is on the allowlist; they
  # additionally see the broker review console. Same entrance, one more tab.
  def broker?
    MarketConfig.broker_emails.include?(email.to_s.downcase)
  end

  def high_intent?
    intent.to_s.start_with?("high")
  end

  # Build the neutral buyer signal hash IntentTriage reads, from the profile
  # columns. Only allow-listed keys; empty values are dropped so they don't count.
  def buyer_signals
    {
      "preapproval"        => (pre_approved.to_s == "yes" ? "true" : ""),
      "move_timeline_days" => move_timeline_days&.to_s.to_s,
      "budget"             => budget_cents&.to_s.to_s
    }.reject { |_, v| v.to_s.strip.empty? }
  end

  # Persist the buyer profile and re-triage. Like record_engagement, the FIRST
  # time the visitor becomes high-intent we route one broker handoff (R5).
  def record_buyer_profile(pre_approved:, move_timeline_days:, budget_cents:)
    assign_attributes(pre_approved: pre_approved.presence,
                      move_timeline_days: move_timeline_days,
                      budget_cents: budget_cents)
    triage = IntentTriage.call(signals: buyer_signals, side: "buyer")
    self.intent = triage.intent
    route_to_broker(triage, "buyer") if triage.high_intent? && !handed_off?
    save!
    triage
  end

  # Record neutral engagement signals on the profile and re-triage. Returns the
  # IntentTriage::Result. The FIRST time a visitor becomes high-intent, route a
  # handoff into the broker queue (once) so a human engages the ready lead.
  def record_engagement(signals:, side: "buyer")
    # Only NEUTRAL signals are ever stored on the profile — a protected-class key
    # is never persisted, let alone consulted (equal service, defense in depth).
    allowed = IntentTriage::NEUTRAL_SIGNALS.fetch(side.to_s, []) + %w[address]
    merged = (engagement_signals || {}).dup
    (signals || {}).each do |k, v|
      next unless allowed.include?(k.to_s)
      merged[k.to_s] = v unless v.to_s.strip.empty?
    end

    triage = IntentTriage.call(signals: merged, side: side)
    assign_attributes(engagement_signals: merged, intent: triage.intent)
    route_to_broker(triage, side) if triage.high_intent? && !handed_off?
    save!
    triage
  end

  private

  def route_to_broker(triage, side)
    lead = Lead.create!(
      side: side,
      address: engagement_signals["address"].presence || "Engagement lead — #{email}",
      contact: email,
      intent: "high"
    )
    EnqueueHandoff.call(
      lead: lead,
      trigger: "high_intent",
      reason: triage.reason,
      recommended_action: "Engage high-intent #{side} (#{name}) — #{triage.signals_used.join(', ')}"
    )
    self.handed_off = true
  end
end
