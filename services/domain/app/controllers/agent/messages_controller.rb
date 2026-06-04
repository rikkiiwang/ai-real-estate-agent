module Agent
  # The sidebar agent endpoint. Takes a free-text question plus the visitor's
  # current page context (a listing address, when they're looking at one) and
  # runs one turn of the brain's LangGraph orchestrator. Public — the agent is
  # the product's centerpiece and needs no login to ask a grounded question.
  class MessagesController < ApplicationController
    # Test seams: factories returning fake brain clients. Nil in production.
    cattr_accessor :client_factory, :valuation_client_factory

    def create
      @query = params[:query].to_s.strip
      @address = resolved_address
      @listing = Property.where(id: params[:listing_id]).first if params[:listing_id].present?
      return head(:bad_request) if @query.blank?

      @intent = SearchIntent.detect(@query)
      if @intent
        # A browse request ("3-bed under $700k in Mueller") surfaces matching
        # listings into the catalog — Rails-side, no brain round-trip.
        @listings = ListingSearch.new(**@intent.to_search_params).results
      elsif (@price_check = price_check_for(@listing, @query))
        # A pricing question on a listing gets a real comparison: asking price vs
        # Atlas's valuation vs nearby comps, with a plain verdict (see PriceCheck).
      else
        # Everything else is a grounded orchestrator turn (the glass box).
        @result = brain_client.orchestrate(query: @query, address: @address, thread_id: agent_thread_id)
      end

      respond_to do |format|
        format.turbo_stream { render view_for }
        format.html { redirect_back fallback_location: root_path }
      end
    end

    private

    def view_for
      return "search" if @intent
      return "price_check" if @price_check

      "create"
    end

    # Returns a usable PriceCheck::Result for a pricing question on a listing,
    # or nil (falls through to the orchestrator).
    def price_check_for(listing, query)
      return nil unless listing && PriceCheck.pricing_question?(query)

      valuation = valuation_client.valuation(address: listing.address)
      comps = Comp.in_region(listing.region).recent_first.limit(3)
      result = PriceCheck.for(property: listing, valuation: valuation, comps: comps)
      result.usable? ? result : nil
    end

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

    def valuation_client
      factory = self.class.valuation_client_factory
      factory ? factory.call : BrainValuationClient.new
    end
  end
end
