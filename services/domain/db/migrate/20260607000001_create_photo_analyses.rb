# Cached photo analysis for R2: per-listing photo-derived condition + structured
# findings, populated off the request path by `rake vision:analyze` (the only
# thing that spends Anthropic budget). The valuation/UI read this cache.
class CreatePhotoAnalyses < ActiveRecord::Migration[8.1]
  def change
    create_table :photo_analyses do |t|
      t.references :property, foreign_key: true
      t.string :address, null: false
      t.decimal :condition, precision: 4, scale: 3
      t.json :findings, default: []
      t.json :needs_review, default: []
      t.string :provenance
      t.datetime :analyzed_at
      t.timestamps
    end
    add_index :photo_analyses, :address, unique: true
  end
end
