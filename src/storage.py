"""
src/storage.py
Store raw order book snapshots and analysis metrics in CSV.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


class CSVStorage:
    """Store raw order book snapshots and analysis metrics in CSV."""

    def __init__(self, project_root=None):
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent

        self.project_root = Path(project_root)

        self.raw_path = (
            self.project_root / "data" / "raw" / "orderbook.csv"
        )

        self.metrics_path = (
            self.project_root / "data" / "analysis" / "metrics.csv"
        )

        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)

        self.raw_fields = [
            "timestamp_utc",
            "symbol",
            "exchange_timestamp",
            "bids_json",
            "asks_json",
        ]

        # यहां buy_slippage_json और sell_slippage_json जोड़ दिया गया है
        self.metric_fields = [
            "timestamp_utc",
            "best_bid",
            "best_ask",
            "mid_price",
            "spread",
            "spread_percent",
            "bid_contracts",
            "ask_contracts",
            "bid_btc",
            "ask_btc",
            "bid_notional_usd",
            "ask_notional_usd",
            "imbalance",
            "buy_slippage_json",
            "sell_slippage_json",
        ]

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _write_row(path, fields, row):
        file_exists = path.exists() and path.stat().st_size > 0

        with path.open(
            "a",
            newline="",
            encoding="utf-8"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=fields,
                extrasaction="ignore"
            )

            if not file_exists:
                writer.writeheader()

            writer.writerow(row)
            file.flush()

    def write_raw_orderbook(
        self,
        orderbook,
        symbol="BTCUSD",
        exchange_timestamp=None,
        timestamp=None
    ):
        row = {
            "timestamp_utc": timestamp or self._timestamp(),
            "symbol": symbol,
            "exchange_timestamp": exchange_timestamp,
            "bids_json": json.dumps(
                orderbook.get("buy", []),
                separators=(",", ":")
            ),
            "asks_json": json.dumps(
                orderbook.get("sell", []),
                separators=(",", ":")
            ),
        }

        self._write_row(
            self.raw_path,
            self.raw_fields,
            row
        )

    def write_metrics(
        self,
        metrics,
        slippage_results=None,
        timestamp=None
    ):
        slippage_results = slippage_results or {}

        row = {
            "timestamp_utc": timestamp or self._timestamp(),
            **metrics,
            "buy_slippage_json": json.dumps(
                slippage_results.get("buy", {}),
                default=str
            ),
            "sell_slippage_json": json.dumps(
                slippage_results.get("sell", {}),
                default=str
            ),
        }

        self._write_row(
            self.metrics_path,
            self.metric_fields,
            row
        )