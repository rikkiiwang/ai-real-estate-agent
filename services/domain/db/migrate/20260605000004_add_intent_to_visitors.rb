class AddIntentToVisitors < ActiveRecord::Migration[8.1]
  # Intent triaging now lives on the user PROFILE: a visitor carries their triage
  # label + the neutral signals behind it, so the broker can see how ready a lead
  # is. Computed from neutral signals only (Fair-Housing equal service).
  def change
    add_column :visitors, :intent, :string, null: false, default: "low_intent_browser"
    add_column :visitors, :engagement_signals, :json, null: false, default: {}
    add_column :visitors, :handed_off, :boolean, null: false, default: false
  end
end
