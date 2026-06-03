class CreateComps < ActiveRecord::Migration[8.1]
  def change
    create_table :comps do |t|
      # A comp may anchor to a specific property or stand alone by region.
      t.references :property, null: true, foreign_key: true
      t.string :region, null: false
      t.string :address, null: false
      t.decimal :sale_price, precision: 12, scale: 2, null: false
      t.date :sale_date, null: false
      t.decimal :distance_mi, precision: 5, scale: 2
      # Provenance for the cited decision bundle.
      t.string :source_name
      t.string :source_url

      t.timestamps
    end

    add_index :comps, :region
  end
end
