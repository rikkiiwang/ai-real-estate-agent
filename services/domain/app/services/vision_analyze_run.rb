# Capped, cache-first batch that populates the PhotoAnalysis cache from real Claude
# vision (R2). The ONLY thing that spends Anthropic budget — never on a web request.
# `max_calls` caps the number of LISTINGS analyzed per run (each listing may make
# several per-photo calls inside the brain); already-fresh listings are skipped
# without a call. Mirrors PropertyRecordPrewarm's discipline.
class VisionAnalyzeRun
  Result = Struct.new(:analyzed, :skipped_fresh, :skipped_budget, keyword_init: true)

  def initialize(client: BrainVisionClient.new)
    @client = client
  end

  def call(properties:, max_calls:)
    analyzed = 0
    skipped_fresh = 0
    skipped_budget = 0

    properties.each do |p|
      next if p.address.blank?

      existing = PhotoAnalysis.find_by("lower(address) = ?", p.address.downcase)
      if existing&.fresh?
        skipped_fresh += 1
        next
      end
      if analyzed >= max_calls
        skipped_budget += 1
        next
      end

      result = @client.analyze(address: p.address, photo_urls: Array(p.photo_urls))
      next unless result.ok?

      analyzed += 1
      rec = existing || PhotoAnalysis.new(address: p.address)
      rec.assign_attributes(
        property: p,
        findings: result.findings.map { |f| finding_hash(f) },
        needs_review: result.needs_review.map { |f| finding_hash(f) },
        condition: result.condition,
        provenance: result.provenance,
        analyzed_at: Time.current
      )
      rec.save!
    end

    Result.new(analyzed: analyzed, skipped_fresh: skipped_fresh, skipped_budget: skipped_budget)
  end

  private

  def finding_hash(f)
    { "kind" => f.kind, "label" => f.label, "confidence" => f.confidence, "evidence_photo_id" => f.evidence_photo_id }
  end
end
