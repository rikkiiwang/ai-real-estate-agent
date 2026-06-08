module Inbound
  # Twilio inbound SMS webhook. Appends to the sender's thread, orchestrates, and
  # replies with TwiML (Twilio relays it as the SMS reply — no outbound call).
  class SmsController < BaseController
    def create
      result = InboundTurn.call(contact: params[:From], channel: "sms", body: params[:Body].to_s)
      twiml = %(<?xml version="1.0" encoding="UTF-8"?><Response><Message>#{ERB::Util.html_escape(result.reply)}</Message></Response>)
      render xml: twiml
    end
  end
end
