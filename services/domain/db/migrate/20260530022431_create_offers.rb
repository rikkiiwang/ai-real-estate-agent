class CreateOffers < ActiveRecord::Migration[8.1]
  def change
    create_table :offers do |t|
      t.references :lead, null: false, foreign_key: true
      # Property is optional: a seller cash offer can be drafted before a
      # Property record exists for the address.
      t.references :property, null: true, foreign_key: true
      t.string :side, null: false
      t.string :status, null: false, default: "drafting"
      t.decimal :amount, precision: 12, scale: 2

      t.timestamps
    end

    add_index :offers, :status
  end
end
