module Inbound
  # SendGrid Inbound Parse webhook. Appends to the sender's thread, orchestrates,
  # and emails the reply (simulated until SendGrid is configured).
  class EmailController < BaseController
    def create
      result = InboundTurn.call(contact: params[:from], channel: "email", body: params[:text].to_s)
      ChannelTransport.deliver(channel: "email", to: params[:from].to_s, body: result.reply)
      head :ok
    end
  end
end
