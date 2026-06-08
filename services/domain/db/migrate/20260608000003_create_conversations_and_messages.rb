class CreateConversationsAndMessages < ActiveRecord::Migration[8.1]
  def change
    create_table :conversations do |t|
      t.string :contact, null: false
      t.string :name
      t.string :last_channel
      t.timestamps
    end
    add_index :conversations, :contact, unique: true

    create_table :messages do |t|
      t.references :conversation, null: false, foreign_key: true
      t.string :channel, null: false
      t.string :role, null: false
      t.text :body
      t.boolean :ai_disclosed, null: false, default: false
      t.timestamps
    end
  end
end
