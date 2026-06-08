class CreateClosingMilestones < ActiveRecord::Migration[8.1]
  def change
    create_table :closing_milestones do |t|
      t.references :offer, null: false, foreign_key: true
      t.string :milestone, null: false
      t.string :counterparty
      t.string :ping_message
      t.string :ping_status, null: false, default: "simulated"
      t.datetime :recorded_at, null: false
      t.timestamps
    end
    add_index :closing_milestones, [:offer_id, :milestone], unique: true
  end
end
