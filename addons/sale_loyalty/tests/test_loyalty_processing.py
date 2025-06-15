from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

class TestLoyaltyProcessing(TransactionCase):
    def setUp(self):
        super().setUp()

        self.partner = self.env['res.partner'].create({'name': 'Test Customer'})
        self.dummy_partner = self.env['res.partner'].create({'name': 'Dummy Partner'})

        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 20.0,
            'type': 'consu',
        })

        self.discount_product = self.env['product.product'].create({
            'name': 'Discount Product',
            'list_price': 0.0,
            'type': 'service',
        })

        self.tax = self.env['account.tax'].create({
            'name': '15% Tax',
            'amount': 15.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
        })

        self.program = self.env['loyalty.program'].create({
            'name': 'Test Loyalty Program',
            'program_type': 'loyalty',
            'sale_ok': True,
            'applies_on': 'current',
        })

        self.rule = self.env['loyalty.rule'].create({
            'program_id': self.program.id,
            'mode': 'auto',
            'reward_point_amount': 0.1,  # 1 point per $10
            'reward_point_mode': 'money',
        })

        self.reward = self.env['loyalty.reward'].create({
            'program_id': self.program.id,
            'reward_type': 'discount',
            'discount': 0.01,  # $0.01 per point
            'discount_line_product_id': self.discount_product.id,
            'required_points': 10.0,
        })

        self.order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 5.0,
                'price_unit': 20.0,
                'tax_id': [(6, 0, [self.tax.id])],
            })],
        })
        self.env['loyalty.program'].search([('id', '!=', self.program.id)]).write({'active': False})

        self.env.flush_all()

        self.assertTrue(self.order.order_line, "Order should have lines")
        self.assertEqual(self.order.amount_untaxed, 100.0, "Order subtotal should be $100")
        self.assertEqual(self.order.amount_total, 115.0, "Order total should be $115 with tax")

    def test_compute_base_points(self):
        processor = self.env['loyalty.processor']
        self.order.action_confirm()
        points = processor.compute_base_points(self.order, self.program)
        self.assertEqual(points, 10.0, "Should compute 10 points for $100 subtotal")

        draft_order = self.order.copy({'state': 'draft'})
        points = processor.compute_base_points(draft_order, self.program)
        self.assertEqual(points, 0.0, "No points for draft order")

        points = processor.compute_base_points(self.order, False)
        self.assertEqual(points, 0.0, "No points without program")

    def test_apply_program_rules(self):
        processor = self.env['loyalty.processor']
        self.order.action_confirm()

        self.program.trigger_product_ids = [(5, 0, 0)]  # clear first
        base_points = processor.apply_program_rules(self.order, self.program)
        self.assertEqual(base_points, 10.0, "Base points should be 10 for $100 subtotal")

        self.program.trigger_product_ids = [(4, self.product.id)]  # enable bonus
        points = processor.apply_program_rules(self.order, self.program)
        self.assertEqual(points, 15.0, "Should add 5 bonus points for 5 units")

    def test_compute_reward_discount(self):
        processor = self.env['loyalty.processor']
        self.order.action_confirm()

        discount = processor.compute_reward_discount(self.order, self.program, 10.0)
        self.assertEqual(discount, 0.10, "10 points should yield $0.10 discount")

        discount = processor.compute_reward_discount(self.order, self.program, 0.0)
        self.assertEqual(discount, 0.0, "No discount for zero points")

        self.reward.discount_max_amount = 11.5  # cap as percentage of 115.0
        discount = processor.compute_reward_discount(self.order, self.program, 1150.0)
        self.assertEqual(discount, 11.5, "Discount capped at 10% of $115")

    def test_apply_points_to_coupon(self):
        processor = self.env['loyalty.processor']

        coupon = processor.apply_points_to_coupon(self.order, self.program, 10.0)
        self.assertTrue(coupon, "Coupon should be created")
        self.assertEqual(coupon.points, 10.0, "Coupon should have 10 points")
        self.assertEqual(coupon.partner_id, self.partner, "Coupon linked to partner")

        history = self.env['loyalty.history'].search([('card_id', '=', coupon.id)])
        self.assertEqual(history.issued, 10.0, "History should log 10 issued points")

        coupon = processor.apply_points_to_coupon(self.order, self.program, 5.0)
        self.assertEqual(coupon.points, 15.0, "Coupon should have 15 points after update")

    def test_deduct_points_from_coupon(self):
        processor = self.env['loyalty.processor']

        coupon = processor.apply_points_to_coupon(self.order, self.program, 20.0)
        result = processor.deduct_points_from_coupon(self.order, self.program, 10.0)
        self.assertTrue(result, "Coupon should be updated")
        self.assertEqual(coupon.points, 10.0, "Coupon should have 10 points left")

        history = self.env['loyalty.history'].search([
            ('card_id', '=', coupon.id), ('used', '>', 0)
        ])
        self.assertEqual(history.used, 10.0, "History should log 10 used points")

        result = processor.deduct_points_from_coupon(self.order, self.program, 15.0)
        self.assertFalse(result, "Should fail for insufficient points")

    def test_award_points(self):
        self.order.action_confirm()  # Automatically triggers facade.award_points via hook

        coupon = self.env['loyalty.card'].search([
            ('partner_id', '=', self.partner.id),
            ('program_id', '=', self.program.id),
        ])
        self.assertTrue(coupon.exists(), "Coupon should exist after confirmation")
        self.assertEqual(coupon.points, 10.0, "Coupon should have 10 points")

        # New customer test
        no_partner_order = self.order.copy({'partner_id': self.dummy_partner.id})
        no_partner_order.action_confirm()

        coupon = self.env['loyalty.card'].search([
            ('partner_id', '=', self.dummy_partner.id),
            ('program_id', '=', self.program.id),
        ])
        self.assertTrue(coupon.exists(), "Points should be awarded for dummy partner too")

    def test_redeem_points(self):
        facade = self.env['loyalty.facade']

        self.env['loyalty.processor'].apply_points_to_coupon(self.order, self.program, 20.0)

        discount = facade.redeem_points(self.order, 10.0)
        self.assertEqual(discount, 0.10, "10 points should yield $0.10 discount")

        coupon = self.env['loyalty.card'].search([
            ('partner_id', '=', self.partner.id),
            ('program_id', '=', self.program.id),
        ])
        self.assertEqual(coupon.points, 10.0, "Coupon should have 10 points left")

        # Edge case: exceeding max discount
        large_order = self.order.copy({'order_line': [(0, 0, {
            'product_id': self.product.id,
            'product_uom_qty': 1.0,
            'price_unit': 20.0,
            'tax_id': [(6, 0, [self.tax.id])],
        })]})
        large_order.action_confirm()

        self.env['loyalty.processor'].apply_points_to_coupon(large_order, self.program, 1000.0)

        with self.assertRaises(ValidationError):
            facade.redeem_points(large_order, 1000.0)
