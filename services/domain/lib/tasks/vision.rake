namespace :vision do
  # Populate the PhotoAnalysis cache from real Claude vision (R2). Capped + cache-first;
  # spends Anthropic budget (only when ANTHROPIC_API_KEY is set on the brain) — never
  # on a web request. MAX_CALLS caps listings analyzed per run.
  #
  #   rake vision:analyze MAX_CALLS=25
  desc "Analyze listing photos via the brain (Claude vision); capped + cache-first"
  task analyze: :environment do
    max = (ENV["MAX_CALLS"] || 25).to_i
    properties = Property.browsable.limit(200).to_a
    result = VisionAnalyzeRun.new.call(properties: properties, max_calls: max)
    puts "Vision: analyzed #{result.analyzed} listing(s), " \
         "skipped #{result.skipped_fresh} fresh / #{result.skipped_budget} over-budget."
  end
end
