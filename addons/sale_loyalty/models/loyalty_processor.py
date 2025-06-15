from odoo import models, api, fields, _
from odoo.tools import float_round

class LoyaltyProcessor(models.Model):
    _name = 'loyalty.processor'
    _description = 'Loyalty Processor for Point Calculations and Redemption'

    @api.model
    def _get_point_strategy(self, order):
        if not order or not order.partner_id:
            return False
        return self.env[
            'loyalty.premium.strategy' if order.partner_id.customer_rank > 1 else 'loyalty.standard.strategy'
        ]

    @api.model
    def compute_base_points(self, order, program, use_strategy=False):
        if not program or not order or order.state != 'sale' or not order.order_line:
            return 0.0

        if use_strategy:
            strategy = self._get_point_strategy(order)
            if strategy:
                try:
                    points = strategy.compute_points(order, program)
                    return float_round(points, precision_digits=2, rounding_method='DOWN')
                except Exception:
                    pass  # failover

        rule = program.rule_ids.filtered(lambda r: r.mode == 'auto')[:1]
        if not rule:
            return 0.0

        rate = rule.reward_point_amount or 0.0
        mode = rule.reward_point_mode or 'money'

        if mode == 'money':
            amount = sum(
                line.price_subtotal
                for line in order.order_line
                if not line.is_reward_line and not line.combo_item_id
            )
            return float_round(rate * amount, precision_digits=2, rounding_method='DOWN')

        elif mode == 'order':
            return float_round(rate, precision_digits=2, rounding_method='DOWN')

        return 0.0

    @api.model
    def apply_program_rules(self, order, program, use_strategy=False):
        base_points = self.compute_base_points(order, program, use_strategy=use_strategy)
        if not base_points or not order.order_line:
            return 0.0

        bonus_points = 0.0
        if not use_strategy and program.trigger_product_ids:
            ordered_products = order.order_line.mapped('product_id')
            if any(p in program.trigger_product_ids for p in ordered_products):
                bonus_points = sum(
                    line.product_uom_qty
                    for line in order.order_line
                    if line.product_id in program.trigger_product_ids
                )

        return float_round(base_points + bonus_points, precision_digits=2, rounding_method='DOWN')

    @api.model
    def compute_reward_discount(self, order, program, points_to_redeem):
        if not program or points_to_redeem <= 0 or not order:
            return 0.0

        reward = program.reward_ids.filtered(lambda r: r.reward_type == 'discount')[:1]
        if not reward:
            return 0.0

        per_point = reward.discount or 0.01
        max_discount = order.amount_total * (reward.discount_max_amount / 100.0 if reward.discount_max_amount else 1.0)
        discount = min(points_to_redeem * per_point, max_discount)

        return float_round(discount, precision_digits=2, rounding_method='DOWN')

    @api.model
    def apply_points_to_coupon(self, order, program, points):
        if points <= 0 or not order.partner_id:
            return False

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
            print("Coupon found, updating points: ", coupon.points, "->", coupon.points + points)
            coupon.sudo().write({'points': coupon.points + points})

        self.env['loyalty.history'].sudo().create({
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
        if points_to_redeem <= 0 or not order.partner_id:
            return False

        coupon = self.env['loyalty.card'].search([
            ('partner_id', '=', order.partner_id.id),
            ('program_id', '=', program.id),
            ('points', '>=', points_to_redeem),
        ], limit=1)

        if coupon:
            coupon.sudo().write({'points': coupon.points - points_to_redeem})
            self.env['loyalty.history'].sudo().create({
                'order_id': order.id,
                'order_model': 'sale.order',
                'description': _("Order %s", order.display_name),
                'card_id': coupon.id,
                'issued': 0.0,
                'used': points_to_redeem,
            })
            return coupon
        return False
