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

ActiveRecord::Schema[8.1].define(version: 2026_05_30_022436) do
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
    t.integer "lead_id", null: false
    t.integer "property_id"
    t.string "side", null: false
    t.string "status", default: "drafting", null: false
    t.datetime "updated_at", null: false
    t.index ["lead_id"], name: "index_offers_on_lead_id"
    t.index ["property_id"], name: "index_offers_on_property_id"
    t.index ["status"], name: "index_offers_on_status"
  end

  create_table "properties", force: :cascade do |t|
    t.string "address", null: false
    t.datetime "created_at", null: false
    t.string "state", default: "acquired", null: false
    t.datetime "updated_at", null: false
  end

  add_foreign_key "consents", "leads"
  add_foreign_key "handoff_packets", "leads"
  add_foreign_key "negotiations", "offers"
  add_foreign_key "offer_metrics", "leads"
  add_foreign_key "offer_metrics", "offers"
  add_foreign_key "offers", "leads"
  add_foreign_key "offers", "properties"
end
