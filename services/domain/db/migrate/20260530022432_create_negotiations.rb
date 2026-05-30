class CreateNegotiations < ActiveRecord::Migration[8.1]
  def change
    create_table :negotiations do |t|
      t.references :offer, null: false, foreign_key: true
      t.decimal :counter_amount
      t.decimal :band_low
      t.decimal :band_high
      t.boolean :within_band
      t.string :note

      t.timestamps
    end
  end
end
