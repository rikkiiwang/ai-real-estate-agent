# The Concierge console: one unified conversation thread that spans Voice / SMS /
# Email / Chat (simulated transport), with live intent triaging. Public, like the
# catalog. The thread is session-scoped so a visitor can demo channel-switching
# without losing context; high-intent contacts route into the broker queue.
class ConciergeController < ApplicationController
  layout "marketplace"

  def show
    conversation
  end

  def create
    channel = params[:channel].to_s
    unless Channel.valid?(channel)
      return render_thread(alert: "Pick a channel.")
    end

    ConciergeService.ingest(
      conversation: conversation,
      channel: channel,
      body: params[:body].to_s.strip.presence || "(no message)",
      signals: collected_signals
    )
    render_thread
  rescue ArgumentError => e
    render_thread(alert: e.message)
  end

  # Start a fresh thread (handy for re-running the demo).
  def reset
    session.delete(:concierge_conversation_id)
    redirect_to concierge_path
  end

  private

  def conversation
    @conversation ||= begin
      convo = Conversation.find_by(id: session[:concierge_conversation_id])
      convo ||= Conversation.create!(
        side: %w[buyer seller].include?(params[:side]) ? params[:side] : "buyer",
        contact: current_visitor&.email,
        name: current_visitor&.name
      )
      session[:concierge_conversation_id] = convo.id
      convo
    end
  end

  # Quick demo toggles map to the neutral buyer signals the triage reads. Nothing
  # outside IntentTriage::NEUTRAL_SIGNALS can be supplied here.
  def collected_signals
    signals = {}
    signals["preapproval"] = "true" if params[:preapproval].present?
    signals["move_timeline_days"] = "20" if params[:move_soon].present?
    signals["address"] = params[:address] if params[:address].present?
    signals["timeline"] = params[:timeline] if params[:timeline].present?
    signals
  end

  def render_thread(alert: nil)
    flash.now[:alert] = alert if alert
    respond_to do |format|
      format.turbo_stream { render turbo_stream: turbo_stream.replace("concierge", partial: "concierge/console", locals: { conversation: conversation }) }
      format.html { render :show }
    end
  end
end
