module Broker
  # Base for all broker-facing pages. Gates them behind HTTP basic auth.
  # Credentials come from env (set as Fly secrets in production). When unset
  # (dev/test), auth is skipped so local work and the hermetic test suite are
  # unaffected. The Rails health endpoint (/up) lives on Rails::HealthController,
  # not here, so it stays open for Fly health checks.
  class BaseController < ApplicationController
    before_action :authenticate_broker!

    private

    def authenticate_broker!
      user = ENV["BROKER_DASHBOARD_USER"]
      pass = ENV["BROKER_DASHBOARD_PASSWORD"]
      return if user.blank? || pass.blank? # auth not configured -> open (dev/test)

      authenticate_or_request_with_http_basic("Broker Dashboard") do |u, p|
        ActiveSupport::SecurityUtils.secure_compare(u, user) &
          ActiveSupport::SecurityUtils.secure_compare(p, pass)
      end
    end
  end
end
