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
  end

  # Lightweight consumer login (name + email, no password).
  resource :session, only: %i[new create destroy]

  # Consumer marketplace: browsable listings (buyer workspace).
  namespace :buyer do
    resources :listings, only: %i[index show]
  end

  # Seller workspace (requires a signed-in visitor).
  namespace :seller do
    get "home", to: "home#show"
  end

  # Agent sidebar: one orchestrator turn per posted message.
  namespace :agent do
    resources :messages, only: %i[create]
  end

  # The consumer marketplace is the public front door; the broker dashboard
  # remains reachable at /broker/dashboard.
  root "buyer/listings#index"
end
