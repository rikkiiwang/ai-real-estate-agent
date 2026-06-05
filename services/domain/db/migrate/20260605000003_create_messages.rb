class CreateMessages < ActiveRecord::Migration[8.1]
  # One turn in a conversation thread, tagged with the channel it arrived on
  # (voice/sms/email/chat) so the same thread carries across channels.
  def change
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
