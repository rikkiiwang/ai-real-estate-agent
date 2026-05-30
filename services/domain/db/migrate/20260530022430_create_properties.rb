class CreateProperties < ActiveRecord::Migration[8.1]
  def change
    create_table :properties do |t|
      t.string :address, null: false
      # Lifecycle state: acquired -> listed -> under_offer -> sold
      t.string :state, null: false, default: "acquired"

      t.timestamps
    end
  end
end
