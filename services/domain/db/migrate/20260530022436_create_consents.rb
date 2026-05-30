class CreateConsents < ActiveRecord::Migration[8.1]
  def change
    create_table :consents do |t|
      t.references :lead, null: false, foreign_key: true
      # The outreach medium this consent governs (voice / sms / chat / email).
      t.string :channel, null: false
      # Affirmative opt-in is REQUIRED before any outreach (consent-first).
      t.boolean :opted_in, null: false, default: false
      # Stamped the instant a consumer opts out; presence suppresses outreach.
      t.datetime :opted_out_at
      # Do-Not-Contact flag — an absolute block independent of opt-in state.
      t.boolean :dnc, null: false, default: false

      t.timestamps
    end

    # One consent record per (lead, channel): the resolvable consent for a
    # contact attempt on a given channel.
    add_index :consents, %i[lead_id channel], unique: true
  end
end
