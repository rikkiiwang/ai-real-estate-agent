class DropConciergeTables < ActiveRecord::Migration[8.1]
  # The standalone Concierge surface was folded into the Ask Atlas chatbot; its
  # persisted thread is no longer used (intent now lives on the visitor profile).
  def up
    drop_table :messages, if_exists: true
    drop_table :conversations, if_exists: true
  end

  def down
    raise ActiveRecord::IrreversibleMigration
  end
end
