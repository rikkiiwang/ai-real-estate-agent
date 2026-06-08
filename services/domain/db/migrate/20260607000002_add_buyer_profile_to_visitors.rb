class AddBuyerProfileToVisitors < ActiveRecord::Migration[8.1]
  def change
    add_column :visitors, :pre_approved, :string          # "yes" / "no" / "unsure" / nil
    add_column :visitors, :move_timeline_days, :integer    # 7 / 30 / 90 / nil
    add_column :visitors, :budget_cents, :integer          # optional
  end
end
