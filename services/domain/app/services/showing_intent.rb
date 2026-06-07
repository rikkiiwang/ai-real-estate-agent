# Rails-side runtime matcher for tour/inspection intent in a sidebar message —
# the mirror of the brain's canonical `classify_scheduling_intent` (same word
# list), used so the agent can answer "can I tour this Friday?" with real,
# collision-aware slots without a brain round-trip. Word-boundary anchored so
# "contour"/"detour"/"review"/"revisit" never false-match. Reads ONLY scheduling
# intent — blind to protected attributes (Fair-Housing safe).
class ShowingIntent
  TOUR = /\b(?:tour(?:s|ing|ed)?|showing|visit(?:s|ing|ed)?|walk\s*through|view(?:ing|ed|s)?|see\ the\ (?:house|home|place))\b/i
  INSPECTION = /\b(?:inspection|inspector|inspect)\b/i

  Result = Struct.new(:kind, keyword_init: true)

  # Returns a Result (kind: "tour"|"inspection") when the message reads like a
  # scheduling request, else nil. Inspection wins when both appear.
  def self.detect(text)
    s = text.to_s
    inspection = s.match?(INSPECTION)
    tour = s.match?(TOUR)
    return nil unless inspection || tour

    Result.new(kind: inspection ? "inspection" : "tour")
  end
end
