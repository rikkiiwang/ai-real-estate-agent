module Broker
  # Broker actions on requested showings: confirm or decline. Confirming assigns
  # the broker and re-checks ShowingScheduler.slot_free? (excluding this
  # appointment) so a broker is never double-booked across properties; a live
  # conflict is refused, not silently overwritten. Behind require_broker.
  class AppointmentsController < BaseController
    def confirm
      appt = Appointment.find(params[:id])
      broker = current_visitor.email

      unless ShowingScheduler.slot_free?(property: appt.property, starts_at: appt.starts_at,
                                         ends_at: appt.ends_at, broker_email: broker, excluding: appt.id)
        AuditEvent.record_rail_trip(kind: "showing_conflict", decision: "blocked", subject: appt,
          detail: "confirm refused: #{broker} is already booked at #{appt.starts_at.iso8601}")
        return redirect_to broker_dashboard_path,
          alert: "That slot now conflicts with another showing — ask the buyer to pick another time."
      end

      appt.update!(status: "confirmed", confirmed_at: Time.current, broker_email: broker)
      AuditEvent.record_rail_trip(kind: "showing_confirmed", decision: "confirmed", subject: appt,
        detail: "#{appt.kind} at #{appt.starts_at.iso8601} for #{appt.property.address}")
      redirect_to broker_dashboard_path, notice: "Showing confirmed."
    end

    def decline
      appt = Appointment.find(params[:id])
      appt.update!(status: "declined", declined_at: Time.current)
      AuditEvent.record_rail_trip(kind: "showing_declined", decision: "declined", subject: appt,
        detail: "#{appt.kind} at #{appt.starts_at.iso8601} for #{appt.property.address}")
      redirect_to broker_dashboard_path, notice: "Showing declined."
    end

    def complete
      appt = Appointment.find(params[:id])
      appt.update!(status: "completed")
      AuditEvent.record_rail_trip(kind: "showing_completed", decision: "completed", subject: appt,
        detail: "#{appt.kind} for #{appt.property.address}")

      # A completed inspection on a resolvable deal clears the first closing
      # milestone (R10) — same coordinator as the broker button.
      if appt.kind == "inspection" && (deal = appt.resolve_offer)
        ClosingOrchestration.record(offer: deal, milestone: "inspection_cleared")
      end

      redirect_to broker_dashboard_path, notice: "Appointment marked completed."
    end
  end
end
