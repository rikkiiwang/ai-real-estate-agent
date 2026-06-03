require "test_helper"

class VisitorTest < ActiveSupport::TestCase
  test "requires name and a valid email" do
    assert_not Visitor.new(name: "", email: "x@y.com").valid?
    assert_not Visitor.new(name: "Jo", email: "not-an-email").valid?
    assert Visitor.new(name: "Jo", email: "jo@example.com").valid?
  end

  test "normalizes and de-dupes email case-insensitively" do
    Visitor.create!(name: "Jo", email: "Jo@Example.com")
    dup = Visitor.new(name: "Jo2", email: "jo@example.com")
    assert_not dup.valid?
  end

  test "sign_in creates a new visitor" do
    visitor = Visitor.sign_in(name: "Pat", email: "pat@example.com")
    assert visitor.persisted?
    assert_equal "pat@example.com", visitor.email
  end

  test "sign_in returns the existing visitor for a known email" do
    first = Visitor.sign_in(name: "Pat", email: "pat@example.com")
    again = Visitor.sign_in(name: "Pat", email: "PAT@example.com")
    assert_equal first.id, again.id
  end

  test "sign_in with a bad email does not persist" do
    visitor = Visitor.sign_in(name: "Pat", email: "nope")
    assert_not visitor.persisted?
  end
end
