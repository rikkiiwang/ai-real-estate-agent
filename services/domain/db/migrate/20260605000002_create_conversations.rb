class CreateConversations < ActiveRecord::Migration[8.1]
  # The unified, cross-channel engagement thread (Concierge). One conversation
  # per contact; messages from any channel append to it. `signals` caches the
  # neutral fields collected so far; `intent` caches the latest triage label.
  def change
    create_table :conversations do |t|
      t.string :contact
      t.string :name
      t.string :side, null: false, default: "buyer"
      t.json :signals, null: false, default: {}
      t.string :intent, null: false, default: "low_intent_browser"
      t.boolean :handed_off, null: false, default: false
      t.timestamps
    end
  end
end
