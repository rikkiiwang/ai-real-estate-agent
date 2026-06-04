class CreateMarketSnapshots < ActiveRecord::Migration[8.1]
  def change
    create_table :market_snapshots do |t|
      t.string :area, null: false           # e.g. "Austin 78704"
      t.string :zip
      t.decimal :median_price, precision: 12, scale: 2
      t.decimal :avg_price_per_sqft, precision: 8, scale: 2
      t.integer :total_listings
      t.integer :new_listings
      t.decimal :avg_days_on_market, precision: 6, scale: 1
      t.date :as_of                          # the feed's lastUpdatedDate
      t.string :source, null: false, default: "RentCast"

      t.timestamps
    end

    add_index :market_snapshots, :zip, unique: true
  end
end
