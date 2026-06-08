module Buyer
  # The buyer's qualification profile (financing / timeline / budget). Replaces
  # the per-message checkboxes: this is profile data, captured once and editable.
  # Saving re-runs IntentTriage and routes a high-intent lead to the broker (R5).
  class ProfilesController < ApplicationController
    layout "marketplace"
    before_action :require_visitor

    def edit
      @visitor = current_visitor
    end

    def update
      current_visitor.record_buyer_profile(
        pre_approved: params[:pre_approved],
        move_timeline_days: params[:move_timeline_days].presence&.to_i,
        budget_cents: dollars_to_cents(params[:budget])
      )
      redirect_to edit_buyer_profile_path, notice: "Profile saved — Atlas will tailor its help."
    end

    private

    def require_visitor
      redirect_to new_session_path unless signed_in?
    end

    def dollars_to_cents(raw)
      d = raw.to_s.gsub(/[^\d]/, "")
      d.empty? ? nil : d.to_i * 100
    end
  end
end
