require "test_helper"

class AgentHistoryTest < ActionDispatch::IntegrationTest
  test "a signed-in visitor sees their prior cross-channel thread in the sidebar" do
    post session_path, params: { name: "Bea", email: "bea@example.com" }
    convo = Conversation.for(contact: "bea@example.com")
    convo.append(channel: "chat", role: "user", body: "how much is it worth")
    convo.append(channel: "sms", role: "agent", body: "About $610k.")

    get buyer_listings_path
    assert_response :success
    assert_match "how much is it worth", @response.body
    assert_match "About $610k.", @response.body
    assert_match(/agent-channel">sms/, @response.body)   # the channel tag is shown
  end
end
