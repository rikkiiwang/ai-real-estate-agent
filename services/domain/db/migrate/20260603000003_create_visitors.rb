class CreateVisitors < ActiveRecord::Migration[8.1]
  def change
    create_table :visitors do |t|
      t.string :name, null: false
      t.string :email, null: false

      t.timestamps
    end

    add_index :visitors, :email, unique: true
  end
end
