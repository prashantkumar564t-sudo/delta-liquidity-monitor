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
        self.assertEqual(result["best_bid"], 100.0)
        self.assertEqual(result["best_ask"], 100.5)
        self.assertEqual(result["spread"], 0.5)
        self.assertEqual(result["mid_price"], 100.25)
        self.assertEqual(result["bid_contracts"], 30)
        self.assertEqual(result["ask_contracts"], 40)
        self.assertAlmostEqual(result["bid_btc"], 0.03)
        self.assertAlmostEqual(result["ask_btc"], 0.04)

    def test_imbalance_bounds(self):
        result = self.analyzer.analyze(self.sample_orderbook)
        imbalance = result["imbalance"]
        self.assertGreaterEqual(imbalance, -1.0)
        self.assertLessEqual(imbalance, 1.0)
        # Expected: (30 - 40) / (30 + 40) = -10 / 70 = -0.142857...
        self.assertAlmostEqual(imbalance, -10 / 70, places=5)

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
