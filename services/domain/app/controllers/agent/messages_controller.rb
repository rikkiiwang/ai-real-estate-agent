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

      @channel = Channel.valid?(params[:channel]) ? params[:channel] : "chat"

      # Omnichannel (R4): a signed-in visitor's turns persist on one durable
      # cross-channel thread; the brain is keyed to it so context carries across
      # channels. Anonymous use stays ephemeral (no contact, no thread).
      @conversation = current_visitor && Conversation.for(contact: current_visitor.email, name: current_visitor.name)
      @conversation&.append(channel: @channel, role: "user", body: @query,
                            ai_disclosed: Channel.mandatory_disclosure?(@channel))

      if handle_insight
        # A suggested-prompt chip: a deterministic, cited, DB-only answer about the
        # pinned listing (no brain round-trip). Sets the ivar its view reads.
      elsif (@intent = SearchIntent.detect(@query))
        # A browse request ("3-bed under $700k in Mueller") surfaces matching
        # listings into the catalog — Rails-side, no brain round-trip.
        @listings = ListingSearch.new(**@intent.to_search_params).results
      elsif (@price_check = price_check_for(@listing, @query))
        # A pricing question on a listing gets a real comparison: asking price vs
        # Atlas's valuation vs nearby comps, with a plain verdict (see PriceCheck).
      elsif (@showing = showing_for(@listing, @query))
        # A scheduling request ("can I tour this Friday?") on a pinned listing
        # surfaces real, collision-aware slots (R6) — Rails-side, no brain round-trip.
      else
        # Everything else is a grounded orchestrator turn (the glass box).
        @result = brain_client.orchestrate(query: @query, address: @address, thread_id: thread_id)
        # On an out-of-band channel (SMS/Email) the reply is "delivered" through
        # the transport seam — simulated until a real carrier is configured.
        @delivery = ChannelTransport.deliver(channel: @channel, to: current_visitor&.email || "buyer", body: @result.message)
      end

      # Record the agent's turn on the durable thread (full text for chat/
      # orchestrate, a one-line summary for card answers).
      if @conversation
        @conversation.append(channel: @channel, role: "agent",
          body: AgentReplySummary.line(result: @result, price_check: @price_check,
            neighborhood: @neighborhood, photo_insight: @photo_insight, showing: @showing,
            listings: @listings, insight_key: @insight_key, query: @query, address: @address),
          ai_disclosed: Channel.mandatory_disclosure?(@channel))
      end

      respond_to do |format|
        format.turbo_stream { render view_for }
        format.html { redirect_back fallback_location: root_path }
      end
    end

    private

    # A suggested-prompt chip carries an explicit `insight` key + a pinned
    # listing → a deterministic, cited answer from data we already hold. Returns
    # true when handled (sets the ivar its view reads), false to fall through.
    def handle_insight
      @insight_key = params[:insight].to_s
      return false unless @listing && %w[price neighborhood photos tour].include?(@insight_key)

      case @insight_key
      when "price"        then @price_check = price_check_for(@listing, @query, force: true)
      when "neighborhood" then @neighborhood = CrossSourceReconciliation.for(property: @listing)
      when "photos"       then @photo_insight = PhotoAnalysis.find_by("lower(address) = ?", @listing.address.downcase)
      when "tour"
        @showing_kind = "tour"
        @showing = ShowingScheduler.available_slots(property: @listing, now: Time.current, kind: "tour")
      end
      true
    end

    def view_for
      return "neighborhood" if @insight_key == "neighborhood"
      return "photos" if @insight_key == "photos"
      return "search" if @intent
      return "price_check" if @price_check
      return "showing" if @showing

      "create"
    end

    # Returns a ShowingScheduler::Result of real available slots when the message
    # is a scheduling request on a pinned listing, else nil (falls through to the
    # orchestrator). Honest even when empty — surfaces the blackout/no-openings
    # reason rather than a generic answer. Sets @showing_kind for the view.
    def showing_for(listing, query)
      intent = listing && ShowingIntent.detect(query)
      return nil unless intent

      @showing_kind = intent.kind
      ShowingScheduler.available_slots(property: listing, now: Time.current, kind: intent.kind)
    end

    # Returns a usable PriceCheck::Result for a pricing question on a listing,
    # or nil (falls through to the orchestrator).
    def price_check_for(listing, query, force: false)
      return nil unless listing && (force || PriceCheck.pricing_question?(query))

      @valuation = ValuationAssembly.new(address: listing.address, client: valuation_client).call
      comps = Comp.in_region(listing.region).recent_first.limit(3)
      result = PriceCheck.for(property: listing, valuation: @valuation, comps: comps)
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

    # The brain thread handle: the durable conversation for a signed-in visitor,
    # else an ephemeral per-session id for anonymous use.
    def thread_id
      @conversation&.thread_id || (session[:agent_thread_id] ||= SecureRandom.uuid)
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
