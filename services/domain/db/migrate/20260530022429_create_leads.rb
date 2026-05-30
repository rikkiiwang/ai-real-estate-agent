class CreateLeads < ActiveRecord::Migration[8.1]
  def change
    create_table :leads do |t|
      t.string :side, null: false
      t.string :address, null: false
      t.string :contact
      t.string :intent, null: false, default: "unknown"

      t.timestamps
    end
  end
end
