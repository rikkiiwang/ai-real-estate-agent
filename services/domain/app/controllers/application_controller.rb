class ApplicationController < ActionController::Base
  # Only allow modern browsers supporting webp images, web push, badges, import maps, CSS nesting, and CSS :has.
  allow_browser versions: :modern

  # Changes to the importmap will invalidate the etag for HTML responses
  stale_when_importmap_changes

  # NOTE: brokers use the same consumer login as everyone else; a visitor whose
  # email is on the broker allowlist additionally sees the "Dashboard" tab and
  # may reach Broker::BaseController pages (require_login + require_broker). Open
  # browsing of the catalog needs no login at all.

  helper_method :current_visitor, :signed_in?, :broker_signed_in?

  private

  def current_visitor
    @current_visitor ||= Visitor.find_by(id: session[:visitor_id]) if session[:visitor_id]
  end

  def signed_in?
    current_visitor.present?
  end

  def broker_signed_in?
    current_visitor&.broker?
  end
end
