import csv
import json
import tempfile
import unittest

from src.storage import CSVStorage


class TestCSVStorage(unittest.TestCase):
    """Test suite for CSV snapshot and metrics persistence."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = CSVStorage(project_root=self.temp_dir.name)

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

        self.sample_metrics = {
            "best_bid": 100.0,
            "best_ask": 100.5,
            "mid_price": 100.25,
            "spread": 0.5,
            "spread_percent": 0.49875,
            "bid_contracts": 30,
            "ask_contracts": 40,
            "bid_btc": 0.03,
            "ask_btc": 0.04,
            "bid_notional_usd": 3.0,
            "ask_notional_usd": 4.02,
            "imbalance": -0.142857,
        }

        self.sample_slippage = {
            "buy": {"executed_contracts": 20, "slippage_usd": 0.25},
            "sell": {"executed_contracts": 20, "slippage_usd": 0.25},
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_and_read_raw_orderbook(self):
        self.storage.write_raw_orderbook(
            self.sample_orderbook,
            symbol="BTCUSD",
            exchange_timestamp=1794142454045000
        )
        self.assertTrue(self.storage.raw_path.exists())

        with self.storage.raw_path.open("r", newline="", encoding="utf-8") as file:
            raw_rows = list(csv.DictReader(file))

        self.assertEqual(len(raw_rows), 1)
        self.assertEqual(raw_rows[0]["symbol"], "BTCUSD")
        saved_bids = json.loads(raw_rows[0]["bids_json"])
        self.assertEqual(saved_bids[0]["price"], "100")

    def test_write_and_read_metrics(self):
        self.storage.write_metrics(
            self.sample_metrics,
            slippage_results=self.sample_slippage
        )
        self.assertTrue(self.storage.metrics_path.exists())

        with self.storage.metrics_path.open("r", newline="", encoding="utf-8") as file:
            metric_rows = list(csv.DictReader(file))

        self.assertEqual(len(metric_rows), 1)
        self.assertEqual(float(metric_rows[0]["spread"]), 0.5)
        saved_buy = json.loads(metric_rows[0]["buy_slippage_json"])
        self.assertEqual(saved_buy["executed_contracts"], 20)


if __name__ == "__main__":
    unittest.main()
