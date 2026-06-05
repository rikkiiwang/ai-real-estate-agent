class AddRetiredAtToProperties < ActiveRecord::Migration[8.1]
  # Lets the importer retire RentCast listings that fall out of the active feed
  # (sold / delisted) so they stop being browsable and badged "Live listing".
  # A reappearing listing clears it again on the next import.
  def change
    add_column :properties, :retired_at, :datetime
    add_index :properties, :retired_at
  end
end
