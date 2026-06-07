module Buyer
  # Request a showing (tour/inspection) for a browsable listing. Public, like the
  # rest of the buyer catalog — a visitor needn't log in to ask for a tour. The
  # slot is re-checked for collisions at write time (ShowingScheduler.slot_free?)
  # and the model has a backstop guard, so a just-taken slot is rejected. The
  # request lands in the broker's pending-showings queue (audited); it is not
  # confirmed until a broker acts.
  class ShowingsController < ApplicationController
    layout "marketplace"

    def create
      @listing = Property.browsable.find(params[:listing_id])
      starts_at = parse_time(params[:starts_at])
      kind = Appointment::KINDS.include?(params[:kind]) ? params[:kind] : "tour"

      return redirect_back_unavailable("Please choose an available time.") if starts_at.nil?

      ends_at = starts_at + ShowingScheduler::SLOT_MINUTES.minutes
      unless ShowingScheduler.slot_free?(property: @listing, starts_at: starts_at, ends_at: ends_at)
        return redirect_back_unavailable("That slot was just taken — please pick another.")
      end

      @appointment = Appointment.new(
        property: @listing, kind: kind, status: "requested",
        starts_at: starts_at, ends_at: ends_at,
        requester_name: requester_name, requester_email: requester_email
      )

      if @appointment.save
        AuditEvent.record_rail_trip(
          kind: "showing_requested", decision: "queued", subject: @appointment,
          detail: "#{kind} at #{starts_at.iso8601} for #{@listing.address}"
        )
        redirect_to buyer_listing_path(@listing),
          notice: "#{kind.capitalize} requested for #{format_slot(starts_at)} — pending broker confirmation."
      else
        redirect_back_unavailable(@appointment.errors.full_messages.to_sentence.presence || "Could not request that showing.")
      end
    end

    private

    def redirect_back_unavailable(message)
      redirect_to buyer_listing_path(@listing), alert: message
    end

    def parse_time(value)
      return nil if value.blank?

      Time.iso8601(value.to_s)
    rescue ArgumentError
      Time.zone.parse(value.to_s)
    end

    def format_slot(time)
      time.strftime("%a %b %-d, %-l:%M %p")
    end

    def requester_name
      current_visitor&.name.presence || params[:requester_name].presence
    end

    def requester_email
      current_visitor&.email.presence || params[:requester_email].presence
    end
  end
end
