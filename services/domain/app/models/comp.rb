class Comp < ApplicationRecord
  # A nearby recent sale used as a cited comparable in the buyer decision
  # bundle. May anchor to a specific property or stand alone by region.
  belongs_to :property, optional: true

  validates :region, presence: true
  validates :address, presence: true
  validates :sale_price, numericality: { greater_than: 0 }
  validates :sale_date, presence: true

  scope :in_region, ->(region) { where(region: region) }
  scope :recent_first, -> { order(sale_date: :desc) }
end
