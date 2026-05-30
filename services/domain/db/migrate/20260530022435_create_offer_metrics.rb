class CreateOfferMetrics < ActiveRecord::Migration[8.1]
  def change
    create_table :offer_metrics do |t|
      t.references :offer, null: false, foreign_key: true
      t.references :lead, null: false, foreign_key: true
      t.string :side, null: false
      # Stored so the duration survives even if the lead's created_at or the
      # offer is later mutated: time-to-offer is a recorded fact, not a
      # recomputed view.
      t.integer :seconds_to_offer, null: false
      t.datetime :recorded_at, null: false

      t.timestamps
    end

    add_index :offer_metrics, :side
  end
end
