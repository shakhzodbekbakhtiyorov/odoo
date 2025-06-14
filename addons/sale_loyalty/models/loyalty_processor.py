from odoo import models, api, fields
from odoo.tools import float_round

class LoyaltyProcessor(models.AbstractModel):
    _name = 'loyalty.processor'
    _description = 'Loyalty Processor for Point Calculations and Redemption'

    @api.model
    def compute_base_points(self, order, program):
        """Compute base loyalty points based on order total (e.g., 1 point per $10)."""
        if not program or not order or order.state != 'sale':
            return 0.0
        point_rate = program.reward_point_amount or 0.1  # Default: 1 point per $10
        if program.reward_point_mode == 'money':
            # Extracted from _program_check_compute_points: points based on amount paid
            amount_paid = sum(
                line.price_total
                for line in order.order_line
                if not line.is_reward_line and not line.combo_item_id
            )
            return float_round(point_rate * amount_paid, precision_digits=2, rounding_method='DOWN')
        elif program.reward_point_mode == 'order':
            return point_rate
        return 0.0

    @api.model
    def apply_program_rules(self, order, program):
        """Apply program-specific rules to adjust points (e.g., bonus points)."""
        base_points = self.compute_base_points(order, program)
        if not base_points:
            return 0.0
        # Example rule: bonus points for specific products (simplified from _program_check_compute_points)
        if program.trigger_product_ids:
            ordered_products = order.order_line.mapped('product_id')
            if any(product in program.trigger_product_ids for product in ordered_products):
                base_points += program.reward_point_amount * len(
                    [line for line in order.order_line if line.product_id in program.trigger_product_ids]
                )
        return base_points

    @api.model
    def compute_reward_discount(self, order, program, points_to_redeem):
        """Calculate discount based on redeemed points (e.g., $0.01 per point)."""
        if not program or points_to_redeem <= 0 or not order:
            return 0.0
        # Extracted from _get_reward_values_discount logic
        discount_per_point = program.discount or 0.01  # Default: $0.01 per point
        max_discount = order.amount_total * (program.discount_max_amount / 100.0 if program.discount_max_amount else 1.0)
        discount = min(points_to_redeem * discount_per_point, max_discount)
        return float_round(discount, precision_digits=2, rounding_method='DOWN')

    @api.model
    def apply_points_to_coupon(self, order, program, points):
        """Create or update loyalty card with awarded points."""
        if points <= 0 or not order.partner_id:
            return False
        # Simplified from _add_points_for_coupon
        coupon = self.env['loyalty.card'].search([
            ('partner_id', '=', order.partner_id.id),
            ('program_id', '=', program.id),
        ], limit=1)
        if not coupon:
            coupon = self.env['loyalty.card'].sudo().create({
                'program_id': program.id,
                'partner_id': order.partner_id.id,
                'points': points,
                'order_id': order.id,
            })
        else:
            coupon.points += points
        # Log to loyalty history (from _add_loyalty_history_lines)
        self.env['loyalty.history'].create({
            'order_id': order.id,
            'order_model': 'sale.order',
            'description': _("Order %s", order.display_name),
            'card_id': coupon.id,
            'issued': points,
            'used': 0.0,
        })
        return coupon

    @api.model
    def deduct_points_from_coupon(self, order, program, points_to_redeem):
        """Deduct redeemed points from loyalty card and log to history."""
        if points_to_redeem <= 0 or not order.partner_id:
            return False
        coupon = self.env['loyalty.card'].search([
            ('partner_id', '=', order.partner_id.id),
            ('program_id', '=', program.id),
            ('points', '>=', points_to_redeem),
        ], limit=1)
        if coupon:
            coupon.points -= points_to_redeem
            # Update loyalty history (from _update_loyalty_history)
            self.env['loyalty.history'].create({
                'order_id': order.id,
                'order_model': 'sale.order',
                'description': _("Order %s", order.display_name),
                'card_id': coupon.id,
                'issued': 0.0,
                'used': points_to_redeem,
            })
            return coupon
        return False