class ApplicationController < ActionController::Base
  # Only allow modern browsers supporting webp images, web push, badges, import maps, CSS nesting, and CSS :has.
  allow_browser versions: :modern

  # Changes to the importmap will invalidate the etag for HTML responses
  stale_when_importmap_changes

  # NOTE: broker HTTP basic auth now lives on Broker::BaseController, not here,
  # so the consumer marketplace (open browsing + lightweight visitor login) is
  # never gated behind broker credentials. Consumer login lives in
  # Consumer::BaseController (require_login).
end
