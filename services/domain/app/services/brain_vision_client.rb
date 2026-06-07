require "realestate/v1/realestate_services_pb"

# Calls the brain's Vision.AnalyzePhotos RPC (R2). Used ONLY by the off-request-path
# `rake vision:analyze` task — never on a web request. Degrades gracefully when the
# brain is unreachable. Inject a fake `stub:` in tests.
class BrainVisionClient
  Finding = Struct.new(:kind, :label, :confidence, :evidence_photo_id, keyword_init: true)
  Result = Struct.new(:findings, :condition, :needs_review, :provenance, :error, keyword_init: true) do
    def ok? = error.nil?
  end

  def initialize(stub: nil, addr: nil)
    @stub = stub
    @addr = addr || ENV.fetch("BRAIN_ADDR", "127.0.0.1:50151")
  end

  def analyze(address:, photo_urls:)
    req = Realestate::V1::AnalyzePhotosRequest.new(address: address.to_s)
    Array(photo_urls).each { |u| req.photo_urls << u.to_s }

    resp = stub.analyze_photos(req)
    Result.new(
      findings: resp.findings.map { |f| to_finding(f) },
      condition: resp.condition,
      needs_review: resp.needs_review.map { |f| to_finding(f) },
      provenance: resp.provenance,
      error: nil,
    )
  rescue StandardError => e
    Rails.logger.warn("[brain] vision failed: #{e.class}: #{e.message}")
    Result.new(findings: [], condition: nil, needs_review: [], provenance: nil, error: "vision_unavailable")
  end

  private

  def to_finding(f)
    Finding.new(kind: f.kind, label: f.label, confidence: f.confidence, evidence_photo_id: f.evidence_photo_id)
  end

  def stub
    @stub ||= Realestate::V1::Vision::Stub.new(@addr, :this_channel_is_insecure)
  end
end
