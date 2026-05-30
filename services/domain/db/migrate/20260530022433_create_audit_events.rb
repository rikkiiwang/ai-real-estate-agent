class CreateAuditEvents < ActiveRecord::Migration[8.1]
  # APPEND-ONLY audit log for claim->source decisions and rail trips.
  #
  # Append-only is enforced at the MODEL layer (see AuditEvent). DB-level
  # tamper-evidence (a real hash chain validated in the DB + REVOKE of
  # UPDATE/DELETE privileges from the app role) is a follow-up flagged in
  # review. The columns below carry a lightweight per-row prev_hash chain +
  # content_hash so tampering is detectable, but the enforced guarantee is the
  # model-layer append-only behaviour plus its tests.
  def change
    create_table :audit_events do |t|
      t.string :kind, null: false
      t.string :subject_type
      t.string :subject_id
      t.text :claim
      t.string :source_id
      t.string :decision
      t.text :detail
      t.string :content_hash, null: false
      t.string :prev_hash

      t.timestamps
    end
  end
end
