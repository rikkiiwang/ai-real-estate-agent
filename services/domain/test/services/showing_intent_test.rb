require "test_helper"

class ShowingIntentTest < ActiveSupport::TestCase
  test "detects tour phrasings as kind tour" do
    [
      "Can I tour this house?",
      "I want to see the home",
      "book a viewing",
      "When can I visit?",
      "I'd like to schedule a showing",
      "can I walk through it?",
    ].each do |q|
      result = ShowingIntent.detect(q)
      assert result, q
      assert_equal "tour", result.kind, q
    end
  end

  test "detects inspection phrasings as kind inspection" do
    ["set up an inspection", "can the inspector come Tuesday?", "I want to inspect the property"].each do |q|
      assert_equal "inspection", ShowingIntent.detect(q).kind, q
    end
  end

  test "inspection wins when both signals appear" do
    assert_equal "inspection", ShowingIntent.detect("Can I tour and also schedule an inspection?").kind
  end

  test "non-scheduling messages return nil" do
    [
      "what's it worth?",
      "is this priced well?",
      "the contour of the lot is gentle",  # not 'tour'
      "we took a detour past it",           # not 'tour'
      "please review the disclosure",       # not 'view'
      "I'll revisit my budget later",       # not 'visit'
      "",
    ].each do |q|
      assert_nil ShowingIntent.detect(q), q
    end
  end
end
