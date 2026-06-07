# Showings/inspections for R6 dynamic scheduling. A requested or confirmed
# appointment occupies a [starts_at, ends_at) slot on a property (and optionally
# a broker), which the collision-avoidance engine subtracts from availability.
class CreateAppointments < ActiveRecord::Migration[8.1]
  def change
    create_table :appointments do |t|
      t.references :property, null: false, foreign_key: true
      t.references :lead, null: true, foreign_key: true
      t.string :kind, null: false, default: "tour"
      t.string :status, null: false, default: "requested"
      t.datetime :starts_at, null: false
      t.datetime :ends_at, null: false
      t.string :requester_name
      t.string :requester_email
      t.string :broker_email
      t.text :notes
      t.datetime :confirmed_at
      t.datetime :declined_at
      t.timestamps
    end

    add_index :appointments, [:property_id, :starts_at]
    add_index :appointments, :status
  end
end
