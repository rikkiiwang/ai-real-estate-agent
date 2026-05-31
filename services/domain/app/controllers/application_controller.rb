class ApplicationController < ActionController::Base
  # Only allow modern browsers supporting webp images, web push, badges, import maps, CSS nesting, and CSS :has.
  allow_browser versions: :modern

  # Changes to the importmap will invalidate the etag for HTML responses
  stale_when_importmap_changes

  # Gate the broker dashboard behind HTTP basic auth. Credentials come from env
  # (set as Fly secrets in production). When unset (dev/test), auth is skipped so
  # local work and the hermetic test suite are unaffected. The Rails health
  # endpoint (/up) lives on Rails::HealthController, not this base class, so it
  # stays open for Fly health checks.
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
