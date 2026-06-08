# Maps a sidebar answer to a single line for the conversation thread: the full
# orchestrator message when there is one, else a short summary of the card the
# agent rendered. Pure — no IO.
module AgentReplySummary
  module_function

  def line(result: nil, price_check: nil, neighborhood: nil, photo_insight: nil,
           showing: nil, listings: nil, insight_key: nil, query: nil, address: nil)
    about = address.present? ? " for #{address}" : ""
    return result.message if result
    return "Shared a price check#{about}." if price_check
    return "Shared the neighborhood pulse#{about}." if neighborhood || insight_key == "neighborhood"
    return "Shared what the photos show#{about}." if photo_insight || insight_key == "photos"
    return "Shared available tour times#{about}." if showing
    return "Surfaced #{listings.size} matching listings." if listings.present?

    "Answered: #{query}"
  end
end
