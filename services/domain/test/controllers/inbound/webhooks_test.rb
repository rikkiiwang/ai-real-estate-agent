require "test_helper"

class Inbound::WebhooksTest < ActionDispatch::IntegrationTest
  class FakeBrain
    def orchestrate(**) = Struct.new(:message).new("Here is what I found.")
  end

  setup do
    ENV["INBOUND_WEBHOOK_TOKEN"] = "secret"
    InboundTurn.client_factory = -> { FakeBrain.new }
  end
  teardown do
    ENV.delete("INBOUND_WEBHOOK_TOKEN")
    InboundTurn.client_factory = nil
  end

  test "inbound SMS appends to the thread and replies with TwiML" do
    post inbound_sms_path, params: { token: "secret", From: "+15125550100", Body: "is it a deal?" }
    assert_response :success
    assert_match %r{<Response><Message>Here is what I found\.</Message></Response>}, @response.body
    assert_equal 2, Conversation.for(contact: "+15125550100").messages.count
  end

  test "inbound email appends and triggers a (simulated) reply" do
    post inbound_email_path, params: { token: "secret", from: "buyer@x.com", text: "hello" }
    assert_response :success
    assert_equal 2, Conversation.for(contact: "buyer@x.com").messages.count
  end

  test "a bad token is rejected" do
    post inbound_sms_path, params: { token: "wrong", From: "+1", Body: "x" }
    assert_response :unauthorized
  end
end
