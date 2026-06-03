# Lightweight consumer login: name + email, no password. One identity gets both
# the Buyer and Seller workspaces. Public (does not require login itself).
class SessionsController < ApplicationController
  layout "marketplace"

  def new
    redirect_to(after_sign_in_path) and return if signed_in?
  end

  def create
    visitor = Visitor.sign_in(name: params[:name], email: params[:email])
    if visitor.persisted?
      session[:visitor_id] = visitor.id
      redirect_to after_sign_in_path, notice: "Welcome, #{visitor.name}."
    else
      flash.now[:alert] = visitor.errors.full_messages.to_sentence.presence || "Enter a name and a valid email."
      render :new, status: :unprocessable_entity
    end
  end

  def destroy
    reset_session
    redirect_to root_path, notice: "Signed out."
  end

  private

  def after_sign_in_path
    session.delete(:return_to) || root_path
  end
end
