class Contract < ApplicationRecord
  # A TREC blanks-only contract draft generated when a broker signs an offer,
  # delivered in-app to both parties. Always a draft for review — never an
  # executed, e-signed, or money-moving instrument (R13).
  belongs_to :offer

  validates :status, inclusion: { in: %w[draft] }
  validates :source, inclusion: { in: %w[closer rails_fallback] }

  def blanks
    JSON.parse(form_json || "{}")["blanks"] || {}
  end
end
