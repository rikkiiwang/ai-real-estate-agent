class CreateHandoffPackets < ActiveRecord::Migration[8.1]
  def change
    create_table :handoff_packets do |t|
      t.references :lead, null: false, foreign_key: true
      t.string :trigger, null: false
      t.float :confidence
      t.text :reason
      t.text :transcript
      t.text :recommended_action
      t.string :status, null: false, default: "pending"

      t.timestamps
    end

    add_index :handoff_packets, :status
  end
end
