
import csv
import json
import tempfile

from src.storage import CSVStorage


def main():
    with tempfile.TemporaryDirectory() as temp_dir:

        storage = CSVStorage(project_root=temp_dir)

        sample_orderbook = {
            "buy": [
                {"price": "100", "size": 10},
                {"price": "99.5", "size": 20},
            ],
            "sell": [
                {"price": "100.5", "size": 15},
                {"price": "101", "size": 25},
            ],
        }

        sample_metrics = {
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

        sample_slippage = {
            "buy": {"executed_contracts": 20, "slippage_usd": 0.25},
            "sell": {"executed_contracts": 20, "slippage_usd": 0.25},
        }

        storage.write_raw_orderbook(
            sample_orderbook,
            symbol="BTCUSD",
            exchange_timestamp=1794142454045000
        )

        storage.write_metrics(
            sample_metrics,
            slippage_results=sample_slippage
        )

        with storage.raw_path.open(
            "r", newline="", encoding="utf-8"
        ) as file:
            raw_rows = list(csv.DictReader(file))

        with storage.metrics_path.open(
            "r", newline="", encoding="utf-8"
        ) as file:
            metric_rows = list(csv.DictReader(file))

        assert len(raw_rows) == 1
        assert len(metric_rows) == 1

        saved_bids = json.loads(raw_rows[0]["bids_json"])
        saved_buy = json.loads(metric_rows[0]["buy_slippage_json"])
        saved_sell = json.loads(metric_rows[0]["sell_slippage_json"])

        assert saved_bids[0]["price"] == "100"
        assert saved_buy["executed_contracts"] == 20
        assert saved_sell["executed_contracts"] == 20

        print("RAW CSV:", storage.raw_path)
        print("METRICS CSV:", storage.metrics_path)
        print("Raw Rows:", len(raw_rows))
        print("Metric Rows:", len(metric_rows))
        print("Slippage Data: Verified")

        print("\nCSV STORAGE TEST PASSED!")


if __name__ == "__main__":
    main()
