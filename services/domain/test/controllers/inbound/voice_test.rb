require "test_helper"

class Inbound::VoiceTest < ActionDispatch::IntegrationTest
  class FakeBrain
    def orchestrate(**) = Struct.new(:message).new("Spoken answer.")
  end

  setup do
    ENV["INBOUND_WEBHOOK_TOKEN"] = "secret"
    InboundTurn.client_factory = -> { FakeBrain.new }
  end
  teardown do
    ENV.delete("INBOUND_WEBHOOK_TOKEN")
    InboundTurn.client_factory = nil
  end

  test "voice relay appends a voice turn and returns the reply as JSON" do
    post inbound_voice_path, params: { token: "secret", contact: "voice-abc", text: "what's my home worth?" }
    assert_response :success
    assert_equal "Spoken answer.", JSON.parse(@response.body)["reply"]
    convo = Conversation.for(contact: "voice-abc")
    assert_equal %w[voice voice], convo.messages.map(&:channel)
    assert convo.messages.first.ai_disclosed   # voice mandates disclosure
  end
end
