class AddListingFieldsToProperties < ActiveRecord::Migration[8.1]
  def change
    change_table :properties, bulk: true do |t|
      t.decimal :list_price, precision: 12, scale: 2
      t.integer :beds
      t.decimal :baths, precision: 3, scale: 1
      t.integer :sqft
      t.string :region
      t.integer :year_built
      t.text :description
      # Array of photo URLs, stored as JSON so the column is portable across
      # Postgres (production) and SQLite (test) without native array types.
      t.json :photo_urls
      # Provenance: every listing is a curated static sample, source-labeled.
      t.string :source_name
      t.string :source_url
      t.datetime :captured_at
      t.decimal :lat, precision: 10, scale: 6
      t.decimal :lng, precision: 10, scale: 6
    end

    add_index :properties, :region
    add_index :properties, :list_price
  end
end
