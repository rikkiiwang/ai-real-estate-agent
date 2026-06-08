module Inbound
  # Voice relay: the Go voice service posts each turn here so a phone call joins
  # the same durable thread (R4). Returns the agent reply for the service to speak.
  class VoiceController < BaseController
    def create
      result = InboundTurn.call(contact: params[:contact], channel: "voice", body: params[:text].to_s)
      render json: { reply: result.reply }
    end
  end
end
