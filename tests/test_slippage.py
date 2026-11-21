import unittest
from decimal import Decimal

from src.slippage import SlippageCalculator


class TestSlippageCalculator(unittest.TestCase):
    """Test suite for strict budget order book ladder walking simulator and maker queue model."""

    def setUp(self):
        self.calculator = SlippageCalculator(
            contract_value=0.001,
            taker_fee=0.0005,
            maker_fee=0.0002
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
                self.assertEqual(result["order_type"], "taker")
                self.assertEqual(result["executed_contracts"], 20)
                self.assertLessEqual(result["executed_notional_usd"], Decimal("2.05"))
                self.assertGreaterEqual(result["unfilled_usd"], Decimal(0))
                # Conservation law: executed_notional + unfilled == requested
                self.assertEqual(
                    result["executed_notional_usd"] + result["unfilled_usd"],
                    result["requested_usd"]
                )
                self.assertGreaterEqual(result["taker_fee_usd"], Decimal(0))

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

    def test_maker_queue_at_best_bid(self):
        # Limit buy at best bid (100.0)
        res = self.calculator.simulate_maker(
            self.sample_orderbook, limit_price="100", size_contracts=5, side="buy"
        )
        self.assertEqual(res["order_type"], "maker")
        self.assertEqual(res["executed_contracts"], 5)
        self.assertEqual(res["slippage_usd"], Decimal(0))
        # FIFO queue depth ahead at best bid: 10 contracts already there
        self.assertEqual(res["queue_depth_ahead"], 10)
        # Notional = 100 * 5 * 0.001 = 0.50 USD
        self.assertEqual(res["executed_notional_usd"], Decimal("0.500"))
        # Maker fee = 0.500 * 0.0002 = 0.0001000
        self.assertEqual(res["maker_fee_usd"], Decimal("0.0001000"))

    def test_maker_queue_behind_best_bid(self):
        # Limit buy at 99.5: queue ahead = 10 (at 100) + 20 (at 99.5) = 30
        res = self.calculator.simulate_maker(
            self.sample_orderbook, limit_price="99.5", size_contracts=10, side="buy"
        )
        self.assertEqual(res["queue_depth_ahead"], 30)

    def test_maker_queue_at_best_ask(self):
        # Limit sell at best ask (100.5)
        res = self.calculator.simulate_maker(
            self.sample_orderbook, limit_price="100.5", size_contracts=5, side="sell"
        )
        self.assertEqual(res["order_type"], "maker")
        self.assertEqual(res["queue_depth_ahead"], 10)

    def test_maker_crossing_spread_raises(self):
        # Best ask is 100.5; limit buy at 100.5 or higher crosses the book
        with self.assertRaises(ValueError):
            self.calculator.simulate_maker(
                self.sample_orderbook, limit_price="100.5", size_contracts=5, side="buy"
            )
        # Best bid is 100.0; limit sell at 100.0 or lower crosses the book
        with self.assertRaises(ValueError):
            self.calculator.simulate_maker(
                self.sample_orderbook, limit_price="100.0", size_contracts=5, side="sell"
            )


if __name__ == "__main__":
    unittest.main()
