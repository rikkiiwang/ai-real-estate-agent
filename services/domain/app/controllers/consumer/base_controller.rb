module Consumer
  # Base for consumer pages that require a signed-in visitor (the Seller
  # workspace, making offers, viewing contracts). Open browsing of the catalog
  # does NOT inherit this — it stays public on ApplicationController.
  class BaseController < ApplicationController
    layout "marketplace"
    before_action :require_login

    private

    def require_login
      return if signed_in?

      session[:return_to] = request.fullpath if request.get?
      redirect_to new_session_path, alert: "Sign in to continue."
    end
  end
end
