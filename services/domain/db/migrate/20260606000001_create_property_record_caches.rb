class CreatePropertyRecordCaches < ActiveRecord::Migration[8.1]
  def change
    create_table :property_record_caches do |t|
      t.string :address, null: false
      t.string :region
      t.integer :beds
      t.decimal :baths, precision: 3, scale: 1
      t.integer :sqft
      t.decimal :lot_sqft, precision: 12, scale: 1
      t.integer :year_built
      t.decimal :lat, precision: 10, scale: 6
      t.decimal :lng, precision: 10, scale: 6
      t.decimal :garage_spaces, precision: 4, scale: 1
      t.decimal :tax_assessed_value, precision: 12, scale: 2
      t.datetime :captured_at
      t.timestamps
    end
    add_index :property_record_caches, :address, unique: true
  end
end
