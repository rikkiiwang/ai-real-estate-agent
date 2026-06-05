Rails.application.routes.draw do
  # Define your application routes per the DSL in https://guides.rubyonrails.org/routing.html

  # Reveal health status on /up that returns 200 if the app boots with no exceptions, otherwise 500.
  # Can be used by load balancers and uptime monitors to verify that the app is live.
  get "up" => "rails/health#show", as: :rails_health_check

  # Render dynamic PWA files from app/views/pwa/* (remember to link manifest in application.html.erb)
  # get "manifest" => "rails/pwa#manifest", as: :pwa_manifest
  # get "service-worker" => "rails/pwa#service_worker", as: :pwa_service_worker

  # Broker review/handoff dashboard.
  namespace :broker do
    get "dashboard", to: "dashboard#show"
    resources :offers, only: [] do
      post :sign, on: :member
    end
  end

  # A signed-in visitor's delivered contract drafts.
  resources :contracts, only: %i[index show], controller: "consumer/contracts"

  # Lightweight consumer login (name + email, no password).
  resource :session, only: %i[new create destroy]

  # Consumer marketplace: browsable listings (buyer workspace).
  namespace :buyer do
    resources :listings, only: %i[index show] do
      resource :offer, only: %i[new create]
    end
  end

  # Seller workspace (requires a signed-in visitor).
  namespace :seller do
    get "home", to: "home#show"
    resources :valuations, only: %i[create]
    resources :counters, only: %i[create] # negotiate the cash offer within the band
  end

  # Agent sidebar: one orchestrator turn per posted message.
  namespace :agent do
    resources :messages, only: %i[create]
  end

  # Concierge: the omnichannel engagement console (unified Voice/SMS/Email/Chat
  # thread + intent triaging). Public, like browsing the catalog.
  get "concierge", to: "concierge#show"
  post "concierge/messages", to: "concierge#create", as: :concierge_messages
  post "concierge/reset", to: "concierge#reset", as: :concierge_reset

  # The consumer marketplace is the public front door; the broker dashboard
  # remains reachable at /broker/dashboard.
  root "buyer/listings#index"
end
