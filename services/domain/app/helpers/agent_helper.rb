module AgentHelper
  # Friendly labels for the agent's evidence provenance (mirrors the chat SPA's
  # SOURCE_LABEL map) so citations read in plain language, not internal kinds.
  SOURCE_LABELS = {
    "valuation_run" => "valuation model",
    "valuation" => "valuation model",
    "tcad_appraisal" => "county appraisal (TCAD)",
    "comp" => "comparable sale",
    "comparable_sale" => "comparable sale",
    "listing" => "listing record",
    "market_config" => "market reference",
    "tax_rate" => "county tax rate",
    "mortgage_rate" => "published mortgage rate"
  }.freeze

  def source_label(kind)
    return "source" if kind.blank?

    SOURCE_LABELS.fetch(kind.to_s) { kind.to_s.tr("_", " ") }
  end

  # A claim's verdict badge class.
  def claim_badge_class(label)
    case label.to_s
    when "entailed" then "mk-badge--good"
    when "contradicted" then "mk-badge--bad"
    else "mk-badge--warn"
    end
  end

  def confidence_pct(value)
    "#{(value.to_f * 100).round}%"
  end
end
