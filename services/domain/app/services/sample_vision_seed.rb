# Seeds labeled "(sample)" PhotoAnalysis rows so the R2 "What the photos show"
# panel + the photo-derived condition driver are visible offline (without an
# ANTHROPIC_API_KEY). Idempotent (upsert by address). The real `rake vision:analyze`
# path overwrites these with genuine Claude vision analysis. Demo data only —
# the UI labels the provenance as "sample", exactly like the curated listings.
module SampleVisionSeed
  PROVENANCE = "sample"

  # Plausible value-features rotated per listing so the demo panel isn't uniform.
  FEATURE_POOL = [
    { "kind" => "feature", "label" => "updated_kitchen",    "confidence" => 0.86 },
    { "kind" => "feature", "label" => "hardwood_floors",    "confidence" => 0.80 },
    { "kind" => "feature", "label" => "abundant_natural_light", "confidence" => 0.74 },
    { "kind" => "feature", "label" => "renovated_bathroom", "confidence" => 0.71 },
    { "kind" => "feature", "label" => "mature_landscaping", "confidence" => 0.67 },
    { "kind" => "feature", "label" => "open_floor_plan",    "confidence" => 0.69 },
  ].freeze

  module_function

  def call(properties: Property.browsable)
    count = 0
    properties.to_a.each do |p|
      next if p.address.blank?

      features = features_for(p)
      rec = PhotoAnalysis.find_or_initialize_by(address: p.address)
      rec.assign_attributes(
        property: p,
        findings: features,
        needs_review: [],
        condition: condition_for(features),
        provenance: PROVENANCE,
        analyzed_at: Time.current
      )
      rec.save!
      count += 1
    end
    count
  end

  def features_for(property)
    photo_id = Array(property.photo_urls).first.to_s.presence || "photo-1"
    offset = property.address.to_s.bytes.sum % FEATURE_POOL.size
    FEATURE_POOL.rotate(offset).first(3).map { |f| f.merge("evidence_photo_id" => photo_id) }
  end

  # Mirrors the brain's condition_from_findings (base 0.5 + 0.08*confidence/feature).
  def condition_for(features)
    score = 0.5 + features.sum { |f| 0.08 * f["confidence"].to_f }
    score.clamp(0.0, 1.0).round(3)
  end
end
