import unittest
from decimal import Decimal

from src.orderbook import OrderBookAnalyzer


class TestOrderBookAnalyzer(unittest.TestCase):
    """Test suite for Level-2 order book microstructure analysis."""

    def setUp(self):
        self.analyzer = OrderBookAnalyzer(contract_value=0.001)
        self.sample_orderbook = {
            "buy": [
                {"price": "100", "size": 10},
                {"price": "99.5", "size": 20},
            ],
            "sell": [
                {"price": "100.5", "size": 15},
                {"price": "101", "size": 25},
            ],
        }

    def test_basic_metrics(self):
        result = self.analyzer.analyze(self.sample_orderbook)
        self.assertEqual(result["best_bid"], Decimal(100))
        self.assertEqual(result["best_ask"], Decimal("100.5"))
        self.assertEqual(result["spread"], Decimal("0.5"))
        self.assertEqual(result["mid_price"], Decimal("100.25"))
        self.assertEqual(result["bid_contracts"], 30)
        self.assertEqual(result["ask_contracts"], 40)
        self.assertEqual(result["bid_btc"], Decimal("0.030"))
        self.assertEqual(result["ask_btc"], Decimal("0.040"))

    def test_imbalance_bounds(self):
        result = self.analyzer.analyze(self.sample_orderbook)
        imbalance = result["imbalance"]
        self.assertGreaterEqual(imbalance, Decimal("-1.0"))
        self.assertLessEqual(imbalance, Decimal("1.0"))
        expected_imbalance = Decimal(-10) / Decimal(70)
        self.assertEqual(imbalance, expected_imbalance)

    def test_executable_lots_within_slippage(self):
        # Best ask is 100.5. With max_slippage_pct=0.005 (0.5%), ceiling is 100.5 * 1.005 = 101.0025
        # Both levels (100.5: 15, 101.0: 25) are <= 101.0025 -> total 40 lots
        res = self.analyzer.analyze(self.sample_orderbook, max_slippage_pct=Decimal("0.005"))
        self.assertEqual(res["max_executable_buy_lots"], 40)

        # With max_slippage_pct=0.001 (0.1%), ceiling is 100.5 * 1.001 = 100.6005
        # Only level 100.5 (15 lots) is <= 100.6005
        res_tight = self.analyzer.analyze(self.sample_orderbook, max_slippage_pct=Decimal("0.001"))
        self.assertEqual(res_tight["max_executable_buy_lots"], 15)

    def test_crossed_book_raises(self):
        crossed_book = {
            "buy": [{"price": "101", "size": 10}],
            "sell": [{"price": "100", "size": 10}],
        }
        with self.assertRaises(ValueError):
            self.analyzer.analyze(crossed_book)

    def test_empty_book_raises(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze({"buy": [], "sell": [{"price": "100", "size": 10}]})
        with self.assertRaises(ValueError):
            self.analyzer.analyze({"buy": [{"price": "100", "size": 10}], "sell": []})

    def test_invalid_prices_raise(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze({"buy": [{"price": "0", "size": 10}], "sell": [{"price": "100", "size": 10}]})


if __name__ == "__main__":
    unittest.main()
