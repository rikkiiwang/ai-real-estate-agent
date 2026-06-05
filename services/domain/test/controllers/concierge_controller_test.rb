require "test_helper"

class ConciergeControllerTest < ActionDispatch::IntegrationTest
  test "GET /concierge renders the thread and an intent badge" do
    get concierge_path
    assert_response :success
    assert_match "Conversation", @response.body
    assert_match(/Looky-loo/i, @response.body)
  end

  test "posting a message appends it to the thread" do
    get concierge_path # establishes the session conversation
    post concierge_messages_path, params: { channel: "chat", body: "just browsing" }, as: :turbo_stream
    assert_response :success
    assert_match "just browsing", @response.body
    assert_match "chat", @response.body
  end

  test "switching channel mid-conversation keeps the same thread (OC3/S2)" do
    get concierge_path
    post concierge_messages_path, params: { channel: "chat", body: "first on chat" }, as: :turbo_stream
    post concierge_messages_path, params: { channel: "sms", body: "now on sms" }, as: :turbo_stream
    # both turns are in the one thread
    assert_match "first on chat", @response.body
    assert_match "now on sms", @response.body
  end

  test "pre-approved + near-term move flips to high-intent and shows the broker notice (S3/S4)" do
    get concierge_path
    assert_difference "HandoffPacket.queue.count", 1 do
      post concierge_messages_path,
           params: { channel: "email", body: "ready to buy", preapproval: "1", move_soon: "1" },
           as: :turbo_stream
    end
    assert_match(/High-intent/i, @response.body)
    assert_match(/Routed to the broker queue/i, @response.body)
  end

  test "a voice message shows the mandatory AI-disclosure note" do
    get concierge_path
    post concierge_messages_path, params: { channel: "voice", body: "calling in" }, as: :turbo_stream
    assert_match(/AI disclosure/i, @response.body)
  end

  test "reset starts a fresh thread" do
    get concierge_path
    post concierge_messages_path, params: { channel: "chat", body: "old thread" }, as: :turbo_stream
    post concierge_reset_path
    get concierge_path
    assert_no_match(/old thread/, @response.body)
  end
end
