# sale_loyalty/models/loyalty_point_strategy.py

from odoo import api, models

class PointStrategy(models.AbstractModel):
    _name = 'loyalty.point.strategy'
    _description = 'Base Strategy for Loyalty Point Calculation'

    @api.model
    def compute_points(self, order, program):
        """Compute points for a sale order based on a loyalty program."""
        raise NotImplementedError("Point calculation strategy must implement compute_points.")

class StandardPointStrategy(models.Model):
    _inherit = 'loyalty.point.strategy'
    _name = 'loyalty.standard.strategy'
    _description = 'Standard Loyalty Point Calculation Strategy'

    @api.model
    def compute_points(self, order, program):
        """Calculate points based on standard rate from program rules."""
        rule = program.rule_ids[:1]  # Take first rule for simplicity
        if not rule:
            return 0.0
        if rule.point_mode == 'money':
            return order.amount_untaxed * rule.reward_point_amount
        elif rule.point_mode == 'quantity':
            return sum(line.product_uom_qty for line in order.order_line) * rule.reward_point_amount
        return 0.0

class PremiumPointStrategy(models.Model):
    _inherit = 'loyalty.point.strategy'
    _name = 'loyalty.premium.strategy'
    _description = 'Premium Loyalty Point Calculation Strategy'

    @api.model
    def compute_points(self, order, program):
        print("IAM IN PREMIUM POINT STRATEGY")
        """Calculate points with bonus for premium customers."""
        rule = program.rule_ids[:1]

        base_points = order.amount_untaxed * rule.reward_point_amount
        # Example: 20% bonus for premium customers
        if order.partner_id.customer_rank > 1:  # Assume rank > 1 for premium
            return base_points * 1.2
        return base_points