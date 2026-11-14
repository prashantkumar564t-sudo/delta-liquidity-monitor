"""
src/storage.py
Store raw order book snapshots and analysis metrics in CSV and SQLite WAL.
"""

import csv
import json
import sqlite3
import time
from datetime import datetime, timezone
from decimal import Decimal
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


class SQLiteStorage:
    """High-throughput, lossless SQLite WAL telemetry storage sink."""

    def __init__(self, db_path=None, project_root=None, batch_size=10):
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            if project_root is None:
                project_root = Path(__file__).resolve().parent.parent
            self.db_path = Path(project_root) / "data" / "telemetry.db"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.batch_size = max(1, batch_size)

        self._snapshot_buffer = []
        self._execution_buffer = []

        self._conn = sqlite3.connect(str(self.db_path))
        self._init_db()

    def _init_db(self):
        """Enforce WAL mode, NORMAL sync, memory temp store, and idempotent schema."""
        cursor = self._conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA temp_store = MEMORY;")
        cursor.execute("PRAGMA cache_size = -2000;")  # 2 MB cache to preserve < 30 MB footprint

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS l2_snapshots (
                symbol TEXT NOT NULL,
                timestamp_us INTEGER NOT NULL,
                timestamp_utc TEXT NOT NULL,
                exchange_timestamp INTEGER,
                best_bid TEXT NOT NULL,
                best_ask TEXT NOT NULL,
                mid_price TEXT NOT NULL,
                spread TEXT NOT NULL,
                spread_percent TEXT NOT NULL,
                bid_contracts INTEGER NOT NULL,
                ask_contracts INTEGER NOT NULL,
                bid_btc TEXT NOT NULL,
                ask_btc TEXT NOT NULL,
                bid_notional_usd TEXT NOT NULL,
                ask_notional_usd TEXT NOT NULL,
                imbalance TEXT NOT NULL,
                rtt_latency_ns INTEGER,
                raw_bids_json TEXT NOT NULL,
                raw_asks_json TEXT NOT NULL,
                PRIMARY KEY (symbol, timestamp_us)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_simulations (
                symbol TEXT NOT NULL,
                timestamp_us INTEGER NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                requested_usd TEXT NOT NULL,
                executed_contracts INTEGER NOT NULL,
                executed_btc TEXT NOT NULL,
                executed_notional_usd TEXT NOT NULL,
                average_price TEXT NOT NULL,
                best_price TEXT NOT NULL,
                slippage_usd TEXT NOT NULL,
                slippage_percent TEXT NOT NULL,
                fee_usd TEXT NOT NULL,
                unfilled_usd TEXT NOT NULL,
                fully_executed INTEGER NOT NULL,
                levels_used INTEGER NOT NULL,
                queue_depth_ahead INTEGER,
                PRIMARY KEY (symbol, timestamp_us, side, order_type)
            );
            """
        )
        self._conn.commit()

    @staticmethod
    def _to_text(val):
        """Serialize numeric types to exact string representations for lossless storage."""
        if val is None:
            return ""
        return str(val)

    def write_snapshot_and_metrics(
        self,
        symbol: str,
        orderbook: dict,
        metrics: dict,
        slippage_results: dict = None,
        exchange_timestamp: int = None,
        timestamp_utc: str = None,
        timestamp_us: int = None,
        rtt_latency_ns: int = None
    ):
        """Buffer a complete L2 snapshot and execution simulations for batched commit."""
        now_utc = timestamp_utc or datetime.now(timezone.utc).isoformat()
        now_us = timestamp_us if timestamp_us is not None else int(time.time() * 1_000_000)

        snapshot_row = (
            symbol,
            now_us,
            now_utc,
            exchange_timestamp,
            self._to_text(metrics.get("best_bid")),
            self._to_text(metrics.get("best_ask")),
            self._to_text(metrics.get("mid_price")),
            self._to_text(metrics.get("spread")),
            self._to_text(metrics.get("spread_percent")),
            int(metrics.get("bid_contracts", 0)),
            int(metrics.get("ask_contracts", 0)),
            self._to_text(metrics.get("bid_btc")),
            self._to_text(metrics.get("ask_btc")),
            self._to_text(metrics.get("bid_notional_usd")),
            self._to_text(metrics.get("ask_notional_usd")),
            self._to_text(metrics.get("imbalance")),
            rtt_latency_ns,
            json.dumps(orderbook.get("buy", []), separators=(",", ":")),
            json.dumps(orderbook.get("sell", []), separators=(",", ":")),
        )
        self._snapshot_buffer.append(snapshot_row)

        if slippage_results:
            for side, sim in slippage_results.items():
                if not sim:
                    continue
                order_type = sim.get("order_type", "taker")
                exec_row = (
                    symbol,
                    now_us,
                    side,
                    order_type,
                    self._to_text(sim.get("requested_usd")),
                    int(sim.get("executed_contracts", 0)),
                    self._to_text(sim.get("executed_btc")),
                    self._to_text(sim.get("executed_notional_usd")),
                    self._to_text(sim.get("average_execution_price")),
                    self._to_text(sim.get("best_price")),
                    self._to_text(sim.get("slippage_usd")),
                    self._to_text(sim.get("slippage_percent")),
                    self._to_text(sim.get("taker_fee_usd", sim.get("fee_usd"))),
                    self._to_text(sim.get("unfilled_usd")),
                    1 if sim.get("fully_executed") else 0,
                    int(sim.get("levels_used", 0)),
                    sim.get("queue_depth_ahead")
                )
                self._execution_buffer.append(exec_row)

        if len(self._snapshot_buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        """Execute batched executemany insert with transaction commit."""
        if not self._snapshot_buffer and not self._execution_buffer:
            return

        cursor = self._conn.cursor()
        if self._snapshot_buffer:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO l2_snapshots (
                    symbol, timestamp_us, timestamp_utc, exchange_timestamp,
                    best_bid, best_ask, mid_price, spread, spread_percent,
                    bid_contracts, ask_contracts, bid_btc, ask_btc,
                    bid_notional_usd, ask_notional_usd, imbalance,
                    rtt_latency_ns, raw_bids_json, raw_asks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                self._snapshot_buffer
            )
            self._snapshot_buffer.clear()

        if self._execution_buffer:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO execution_simulations (
                    symbol, timestamp_us, side, order_type, requested_usd,
                    executed_contracts, executed_btc, executed_notional_usd,
                    average_price, best_price, slippage_usd, slippage_percent,
                    fee_usd, unfilled_usd, fully_executed, levels_used,
                    queue_depth_ahead
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                self._execution_buffer
            )
            self._execution_buffer.clear()

        self._conn.commit()

    def close(self):
        """Flush remaining buffered rows and close connection."""
        self.flush()
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
