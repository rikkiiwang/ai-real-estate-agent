class CreateContracts < ActiveRecord::Migration[8.1]
  def change
    create_table :contracts do |t|
      t.references :offer, null: false, foreign_key: true
      t.string :form_id
      t.string :title
      # Filled promulgated-TREC blanks (factual only), serialized as JSON. There
      # is no column for authored clause language — the UPL boundary is structural.
      t.text :form_json
      # "closer" (drafted by the Python Closer) or "rails_fallback".
      t.string :source, null: false, default: "closer"
      # Always a draft for review — no e-signature / execution in scope.
      t.string :status, null: false, default: "draft"
      t.datetime :delivered_at

      t.timestamps
    end
  end
end
