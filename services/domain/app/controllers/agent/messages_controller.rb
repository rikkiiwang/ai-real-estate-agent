module Agent
  # The sidebar agent endpoint. Takes a free-text question plus the visitor's
  # current page context (a listing address, when they're looking at one) and
  # runs one turn of the brain's LangGraph orchestrator. Public — the agent is
  # the product's centerpiece and needs no login to ask a grounded question.
  class MessagesController < ApplicationController
    # Test seam: set a factory returning a fake brain client. Nil in production.
    cattr_accessor :client_factory

    def create
      @query = params[:query].to_s.strip
      @address = resolved_address
      return head(:bad_request) if @query.blank?

      # A browse request ("3-bed under $700k in Mueller") is answered Rails-side
      # by surfacing matching listings into the catalog — fast and reliable, no
      # brain round-trip. Everything else is a grounded orchestrator turn.
      @intent = SearchIntent.detect(@query)
      if @intent
        @listings = ListingSearch.new(**@intent.to_search_params).results
      else
        @result = brain_client.orchestrate(
          query: @query,
          address: @address,
          thread_id: agent_thread_id
        )
      end

      respond_to do |format|
        format.turbo_stream { render @intent ? "search" : "create" }
        format.html { redirect_back fallback_location: root_path }
      end
    end

    private

    # Context-awareness: a listing_id pins the question to that property's
    # address so "is this priced well?" works without the visitor restating it.
    def resolved_address
      if params[:listing_id].present?
        Property.where(id: params[:listing_id]).pick(:address).to_s
      else
        params[:address].to_s
      end
    end

    def agent_thread_id
      session[:agent_thread_id] ||= SecureRandom.uuid
    end

    # Seam for tests to inject a fake brain.
    def brain_client
      factory = self.class.client_factory
      factory ? factory.call : BrainConversationClient.new
    end
  end
end
