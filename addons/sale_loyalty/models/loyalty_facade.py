from odoo import models, api
from odoo.exceptions import ValidationError
from odoo.tools import float_round

class LoyaltyFacade(models.AbstractModel):
    _name = 'loyalty.facade'
    _description = 'Facade for Loyalty Program Operations'

    @api.model
    def award_points(self, order):
        """Award loyalty points to the customer's loyalty card based on the sale order."""
        if not order or order.state != 'sale' or not order.partner_id:
            return False
        programs = self.env['loyalty.program'].search([
            ('active', '=', True),
            ('sale_ok', '=', True),
            ('program_type', '=', 'loyalty'),
            '|', ('pricelist_ids', '=', False), ('pricelist_ids', 'in', order.pricelist_id.id),
        ])
        processor = self.env['loyalty.processor']
        points_awarded = False
        for program in programs:
            points = processor.apply_program_rules(order, program)
            if points > 0:
                coupon = processor.apply_points_to_coupon(order, program, points)
                if coupon:
                    points_awarded = True
        return points_awarded

    @api.model
    def redeem_points(self, order, points_to_redeem):
        """Redeem loyalty points for a discount on the sale order."""
        if not order or points_to_redeem <= 0 or not order.partner_id:
            return 0.0
        programs = self.env['loyalty.program'].search([
            ('active', '=', True),
            ('sale_ok', '=', True),
            ('program_type', '=', 'loyalty'),
            '|', ('pricelist_ids', '=', False), ('pricelist_ids', 'in', order.pricelist_id.id),
        ])
        processor = self.env['loyalty.processor']
        total_discount = 0.0
        for program in programs:
            discount = processor.compute_reward_discount(order, program, points_to_redeem)
            if discount > 0:
                coupon = processor.deduct_points_from_coupon(order, program, points_to_redeem)
                if coupon:
                    total_discount += discount
        if total_discount > order.amount_total:
            raise ValidationError("Loyalty discount (%s) cannot exceed order total (%s)." % (total_discount, order.amount_total))
        return float_round(total_discount, precision_digits=2, rounding_method='DOWN')