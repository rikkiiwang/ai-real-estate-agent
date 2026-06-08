module Inbound
  # Base for provider webhooks. CSRF-exempt (providers can't carry our token) and
  # guarded by a shared secret. Full Twilio-signature / SendGrid validation is the
  # documented production seam.
  class BaseController < ActionController::Base
    skip_forgery_protection
    before_action :verify_token

    private

    def verify_token
      expected = ENV["INBOUND_WEBHOOK_TOKEN"].to_s
      given = (params[:token].presence || request.headers["X-Webhook-Token"]).to_s
      return if expected.present? && ActiveSupport::SecurityUtils.secure_compare(given, expected)

      head :unauthorized
    end
  end
end
