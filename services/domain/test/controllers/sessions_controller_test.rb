require "test_helper"

class SessionsControllerTest < ActionDispatch::IntegrationTest
  test "signing in with name + email creates a visitor and a session" do
    assert_difference -> { Visitor.count }, 1 do
      post session_path, params: { name: "Jordan", email: "jordan@example.com" }
    end
    assert_redirected_to root_path
    follow_redirect!
    assert_match "Jordan", @response.body # greeting in nav
  end

  test "invalid email re-renders the form" do
    post session_path, params: { name: "Jordan", email: "nope" }
    assert_response :unprocessable_entity
  end

  test "both Buyer and Seller workspaces are reachable by the same visitor" do
    post session_path, params: { name: "Jordan", email: "jordan@example.com" }

    get buyer_listings_path
    assert_response :success

    get seller_home_path
    assert_response :success
    assert_match "Seller workspace", @response.body
  end

  test "seller workspace requires login and redirects otherwise" do
    get seller_home_path
    assert_redirected_to new_session_path
  end

  test "browsing the catalog does NOT require login" do
    get buyer_listings_path
    assert_response :success
  end

  test "sign out clears the session" do
    post session_path, params: { name: "Jordan", email: "jordan@example.com" }
    delete session_path
    assert_redirected_to root_path
    get seller_home_path
    assert_redirected_to new_session_path
  end
end
