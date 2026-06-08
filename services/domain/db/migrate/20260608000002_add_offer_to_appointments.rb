class AddOfferToAppointments < ActiveRecord::Migration[8.1]
  def change
    add_reference :appointments, :offer, null: true, foreign_key: true
  end
end
