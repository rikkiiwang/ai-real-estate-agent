module Broker
  # Base for broker-facing pages. Brokers use the SAME consumer login as everyone
  # else; a visitor whose email is on the broker allowlist (MarketConfig) sees the
  # extra "Dashboard" tab and may reach these pages. Server-side gating here is
  # the real boundary — a non-broker visitor can never reach the review queue,
  # tab hidden or not.
  class BaseController < Consumer::BaseController
    before_action :require_broker

    private

    def require_broker
      return if current_visitor&.broker?

      redirect_to root_path, alert: "That area is for licensed brokers."
    end
  end
end
