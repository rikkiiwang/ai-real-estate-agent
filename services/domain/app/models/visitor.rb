class Visitor < ApplicationRecord
  # A lightweight consumer identity — name + email, no password. One identity
  # owns both the Buyer and Seller workspaces (they are parallel contexts, not
  # mutually exclusive roles).
  validates :name, presence: true
  validates :email, presence: true,
                    uniqueness: { case_sensitive: false },
                    format: { with: URI::MailTo::EMAIL_REGEXP }

  normalizes :email, with: ->(e) { e.to_s.strip.downcase }

  # Find an existing visitor by email or create one. Lets a returning visitor
  # sign back in without a password and keep their identity.
  def self.sign_in(name:, email:)
    visitor = find_or_initialize_by(email: email.to_s.strip.downcase)
    visitor.name = name if name.present?
    visitor.save
    visitor
  end
end
