import unittest
from decimal import Decimal
from src.slippage import SlippageCalculator


class TestSlippageCalculator(unittest.TestCase):
    """Test suite for strict budget order book ladder walking simulator."""

    def setUp(self):
        self.calculator = SlippageCalculator(
            contract_value=0.001,
            taker_fee=0.0005
        )
        self.sample_orderbook = {
            "buy": [
                {"price": "100", "size": 10},
                {"price": "99.5", "size": 20},
            ],
            "sell": [
                {"price": "100.5", "size": 10},
                {"price": "101", "size": 20},
                {"price": "101.5", "size": 30},
            ],
        }

    def test_simulation_execution_and_budget_conservation(self):
        for side in ("buy", "sell"):
            with self.subTest(side=side):
                result = self.calculator.simulate(
                    self.sample_orderbook,
                    order_usd=2.05,
                    side=side
                )
                self.assertEqual(result["executed_contracts"], 20)
                self.assertLessEqual(result["executed_notional_usd"], Decimal("2.05"))
                self.assertGreaterEqual(result["unfilled_usd"], Decimal("0"))
                # Conservation law: executed_notional + unfilled == requested
                self.assertEqual(
                    result["executed_notional_usd"] + result["unfilled_usd"],
                    result["requested_usd"]
                )
                self.assertGreaterEqual(result["taker_fee_usd"], Decimal("0"))

    def test_zero_or_negative_order_size_raises(self):
        with self.assertRaises(ValueError):
            self.calculator.simulate(self.sample_orderbook, order_usd=0, side="buy")
        with self.assertRaises(ValueError):
            self.calculator.simulate(self.sample_orderbook, order_usd=-10, side="buy")

    def test_invalid_side_raises(self):
        with self.assertRaises(ValueError):
            self.calculator.simulate(self.sample_orderbook, order_usd=100, side="hold")

    def test_empty_levels_raises(self):
        empty_book = {"buy": [], "sell": []}
        with self.assertRaises(ValueError):
            self.calculator.simulate(empty_book, order_usd=100, side="buy")


if __name__ == "__main__":
    unittest.main()
