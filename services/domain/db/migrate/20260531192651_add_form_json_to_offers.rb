class AddFormJsonToOffers < ActiveRecord::Migration[8.1]
  def change
    add_column :offers, :form_json, :text
  end
end
