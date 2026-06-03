class EnforceOneContractPerOffer < ActiveRecord::Migration[8.1]
  def change
    remove_index :contracts, :offer_id
    add_index :contracts, :offer_id, unique: true
  end
end
