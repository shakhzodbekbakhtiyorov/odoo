from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError

class TestLoyaltyPointStrategy(TransactionCase):
    def setUp(self):
        super().setUp()
        # Create pricelist
        self.pricelist = self.env['product.pricelist'].create({
            'name': 'Test Pricelist',
            'currency_id': self.env.ref('base.USD').id,
        })

        # Create partners
        self.partner = self.env['res.partner'].create({
            'name': 'Standard Customer',
            'customer_rank': 0,
        })

        self.premium_partner = self.env['res.partner'].create({
            'name': 'Premium Customer',
            'customer_rank': 2,
        })

        # Create product
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
            'standard_price': 50.0,
        })

        # Create loyalty program and rule
        self.program = self.env['loyalty.program'].create({
            'name': 'Standard Program',
            'program_type': 'loyalty',
            'sale_ok': True,
            'active': True,
        })

        self.rule = self.env['loyalty.rule'].create({
            'program_id': self.program.id,
            'mode': 'auto',
            'reward_point_amount': 0.1,
            'reward_point_mode': 'money',
        })

        # Create orders
        self.order_standard = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'pricelist_id': self.pricelist.id,
        })

        self.order_standard.write({
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 100.0,
            })]
        })
        self.order_standard.action_confirm()

        self.order_premium = self.env['sale.order'].create({
            'partner_id': self.premium_partner.id,
            'pricelist_id': self.pricelist.id,
        })

        self.order_premium.write({
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 100.0,
            })]
        })
        self.order_premium.action_confirm()

    def test_standard_strategy(self):
        processor = self.env['loyalty.processor']
        points = processor.compute_base_points(self.order_standard, self.program)
        self.assertAlmostEqual(points, 10.0, places=2, msg="Standard strategy should award 10 points.")

    def test_premium_strategy(self):
        processor = self.env['loyalty.processor']
        points = processor.compute_base_points(self.order_premium, self.program)
        self.assertAlmostEqual(points, 12.0, places=2, msg="Premium strategy should award 12 points (20% bonus).")

    def test_apply_program_rules_bonus(self):
        # Simulate trigger product match
        self.program.write({'trigger_product_ids': [(6, 0, [self.product.id])]})
        processor = self.env['loyalty.processor']
        points = processor.apply_program_rules(self.order_standard, self.program)
        self.assertGreater(points, 10.0, msg="Trigger product bonus should increase total points.")

    def test_strategy_fallback(self):
        # Remove rule to trigger fallback
        self.program.rule_ids.unlink()
        processor = self.env['loyalty.processor']
        points = processor.compute_base_points(self.order_standard, self.program)
        self.assertEqual(points, 0.0, msg="Fallback logic should return 0 if no rule or strategy available.")

