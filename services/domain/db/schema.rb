# This file is auto-generated from the current state of the database. Instead
# of editing this file, please use the migrations feature of Active Record to
# incrementally modify your database, and then regenerate this schema definition.
#
# This file is the source Rails uses to define your schema when running `bin/rails
# db:schema:load`. When creating a new database, `bin/rails db:schema:load` tends to
# be faster and is potentially less error prone than running all of your
# migrations from scratch. Old migrations may fail to apply correctly if those
# migrations use external dependencies or application code.
#
# It's strongly recommended that you check this file into your version control system.

ActiveRecord::Schema[8.1].define(version: 2026_06_08_000001) do
  create_table "appointments", force: :cascade do |t|
    t.string "broker_email"
    t.datetime "confirmed_at"
    t.datetime "created_at", null: false
    t.datetime "declined_at"
    t.datetime "ends_at", null: false
    t.string "kind", default: "tour", null: false
    t.integer "lead_id"
    t.text "notes"
    t.integer "property_id", null: false
    t.string "requester_email"
    t.string "requester_name"
    t.datetime "starts_at", null: false
    t.string "status", default: "requested", null: false
    t.datetime "updated_at", null: false
    t.index ["lead_id"], name: "index_appointments_on_lead_id"
    t.index ["property_id", "starts_at"], name: "index_appointments_on_property_id_and_starts_at"
    t.index ["property_id"], name: "index_appointments_on_property_id"
    t.index ["status"], name: "index_appointments_on_status"
  end

  create_table "audit_events", force: :cascade do |t|
    t.text "claim"
    t.string "content_hash", null: false
    t.datetime "created_at", null: false
    t.string "decision"
    t.text "detail"
    t.string "kind", null: false
    t.string "prev_hash"
    t.string "source_id"
    t.string "subject_id"
    t.string "subject_type"
    t.datetime "updated_at", null: false
  end

  create_table "closing_milestones", force: :cascade do |t|
    t.string "counterparty"
    t.datetime "created_at", null: false
    t.string "milestone", null: false
    t.integer "offer_id", null: false
    t.string "ping_message"
    t.string "ping_status", default: "simulated", null: false
    t.datetime "recorded_at", null: false
    t.datetime "updated_at", null: false
    t.index ["offer_id", "milestone"], name: "index_closing_milestones_on_offer_id_and_milestone", unique: true
    t.index ["offer_id"], name: "index_closing_milestones_on_offer_id"
  end

  create_table "comps", force: :cascade do |t|
    t.string "address", null: false
    t.datetime "created_at", null: false
    t.decimal "distance_mi", precision: 5, scale: 2
    t.integer "property_id"
    t.string "region", null: false
    t.date "sale_date", null: false
    t.decimal "sale_price", precision: 12, scale: 2, null: false
    t.string "source_name"
    t.string "source_url"
    t.datetime "updated_at", null: false
    t.index ["property_id"], name: "index_comps_on_property_id"
    t.index ["region"], name: "index_comps_on_region"
  end

  create_table "consents", force: :cascade do |t|
    t.string "channel", null: false
    t.datetime "created_at", null: false
    t.boolean "dnc", default: false, null: false
    t.integer "lead_id", null: false
    t.boolean "opted_in", default: false, null: false
    t.datetime "opted_out_at"
    t.datetime "updated_at", null: false
    t.index ["lead_id", "channel"], name: "index_consents_on_lead_id_and_channel", unique: true
    t.index ["lead_id"], name: "index_consents_on_lead_id"
  end

  create_table "contracts", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.datetime "delivered_at"
    t.string "form_id"
    t.text "form_json"
    t.integer "offer_id", null: false
    t.string "source", default: "closer", null: false
    t.string "status", default: "draft", null: false
    t.string "title"
    t.datetime "updated_at", null: false
    t.index ["offer_id"], name: "index_contracts_on_offer_id", unique: true
  end

  create_table "handoff_packets", force: :cascade do |t|
    t.float "confidence"
    t.datetime "created_at", null: false
    t.integer "lead_id", null: false
    t.text "reason"
    t.text "recommended_action"
    t.string "status", default: "pending", null: false
    t.text "transcript"
    t.string "trigger", null: false
    t.datetime "updated_at", null: false
    t.index ["lead_id"], name: "index_handoff_packets_on_lead_id"
    t.index ["status"], name: "index_handoff_packets_on_status"
  end

  create_table "leads", force: :cascade do |t|
    t.string "address", null: false
    t.string "contact"
    t.datetime "created_at", null: false
    t.string "intent", default: "unknown", null: false
    t.string "side", null: false
    t.datetime "updated_at", null: false
  end

  create_table "market_snapshots", force: :cascade do |t|
    t.string "area", null: false
    t.date "as_of"
    t.decimal "avg_days_on_market", precision: 6, scale: 1
    t.decimal "avg_price_per_sqft", precision: 8, scale: 2
    t.datetime "created_at", null: false
    t.decimal "median_price", precision: 12, scale: 2
    t.integer "new_listings"
    t.string "source", default: "RentCast", null: false
    t.integer "total_listings"
    t.datetime "updated_at", null: false
    t.string "zip"
    t.index ["zip"], name: "index_market_snapshots_on_zip", unique: true
  end


  create_table "negotiations", force: :cascade do |t|
    t.decimal "band_high"
    t.decimal "band_low"
    t.decimal "counter_amount"
    t.datetime "created_at", null: false
    t.string "note"
    t.integer "offer_id", null: false
    t.datetime "updated_at", null: false
    t.boolean "within_band"
    t.index ["offer_id"], name: "index_negotiations_on_offer_id"
  end

  create_table "offer_metrics", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.integer "lead_id", null: false
    t.integer "offer_id", null: false
    t.datetime "recorded_at", null: false
    t.integer "seconds_to_offer", null: false
    t.string "side", null: false
    t.datetime "updated_at", null: false
    t.index ["lead_id"], name: "index_offer_metrics_on_lead_id"
    t.index ["offer_id"], name: "index_offer_metrics_on_offer_id"
    t.index ["side"], name: "index_offer_metrics_on_side"
  end

  create_table "offers", force: :cascade do |t|
    t.decimal "amount", precision: 12, scale: 2
    t.datetime "created_at", null: false
    t.text "form_json"
    t.integer "lead_id", null: false
    t.integer "property_id"
    t.string "side", null: false
    t.string "status", default: "drafting", null: false
    t.datetime "updated_at", null: false
    t.index ["lead_id"], name: "index_offers_on_lead_id"
    t.index ["property_id"], name: "index_offers_on_property_id"
    t.index ["status"], name: "index_offers_on_status"
  end

  create_table "photo_analyses", force: :cascade do |t|
    t.string "address", null: false
    t.datetime "analyzed_at"
    t.decimal "condition", precision: 4, scale: 3
    t.datetime "created_at", null: false
    t.json "findings", default: []
    t.json "needs_review", default: []
    t.integer "property_id"
    t.string "provenance"
    t.datetime "updated_at", null: false
    t.index ["address"], name: "index_photo_analyses_on_address", unique: true
    t.index ["property_id"], name: "index_photo_analyses_on_property_id"
  end

  create_table "properties", force: :cascade do |t|
    t.string "address", null: false
    t.decimal "baths", precision: 3, scale: 1
    t.integer "beds"
    t.datetime "captured_at"
    t.datetime "created_at", null: false
    t.text "description"
    t.decimal "lat", precision: 10, scale: 6
    t.decimal "list_price", precision: 12, scale: 2
    t.decimal "lng", precision: 10, scale: 6
    t.json "photo_urls"
    t.string "region"
    t.datetime "retired_at"
    t.string "source_name"
    t.string "source_url"
    t.integer "sqft"
    t.string "state", default: "acquired", null: false
    t.datetime "updated_at", null: false
    t.integer "year_built"
    t.index ["list_price"], name: "index_properties_on_list_price"
    t.index ["region"], name: "index_properties_on_region"
    t.index ["retired_at"], name: "index_properties_on_retired_at"
  end

  create_table "property_record_caches", force: :cascade do |t|
    t.string "address", null: false
    t.decimal "baths", precision: 3, scale: 1
    t.datetime "captured_at"
    t.datetime "created_at", null: false
    t.decimal "garage_spaces", precision: 4, scale: 1
    t.decimal "lat", precision: 10, scale: 6
    t.decimal "lng", precision: 10, scale: 6
    t.decimal "lot_sqft", precision: 12, scale: 1
    t.integer "beds"
    t.string "region"
    t.integer "sqft"
    t.decimal "tax_assessed_value", precision: 12, scale: 2
    t.datetime "updated_at", null: false
    t.integer "year_built"
    t.index ["address"], name: "index_property_record_caches_on_address", unique: true
  end

  create_table "visitors", force: :cascade do |t|
    t.integer "budget_cents"
    t.datetime "created_at", null: false
    t.string "email", null: false
    t.json "engagement_signals", default: {}, null: false
    t.boolean "handed_off", default: false, null: false
    t.string "intent", default: "low_intent_browser", null: false
    t.integer "move_timeline_days"
    t.string "name", null: false
    t.string "pre_approved"
    t.datetime "updated_at", null: false
    t.index ["email"], name: "index_visitors_on_email", unique: true
  end

  add_foreign_key "appointments", "leads"
  add_foreign_key "appointments", "properties"
  add_foreign_key "closing_milestones", "offers"
  add_foreign_key "photo_analyses", "properties"
  add_foreign_key "comps", "properties"
  add_foreign_key "consents", "leads"
  add_foreign_key "contracts", "offers"
  add_foreign_key "handoff_packets", "leads"
  add_foreign_key "negotiations", "offers"
  add_foreign_key "offer_metrics", "leads"
  add_foreign_key "offer_metrics", "offers"
  add_foreign_key "offers", "leads"
  add_foreign_key "offers", "properties"
end
