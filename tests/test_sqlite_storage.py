import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.storage import SQLiteStorage


class TestSQLiteStorage(unittest.TestCase):
    """Test suite for lossless SQLite WAL telemetry storage sink."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_telemetry.db"
        self.storage = SQLiteStorage(db_path=self.db_path, batch_size=2)

        self.sample_orderbook = {
            "buy": [{"price": "92100.50", "size": 15}],
            "sell": [{"price": "92101.00", "size": 20}],
        }

        self.sample_metrics = {
            "best_bid": Decimal("92100.50"),
            "best_ask": Decimal("92101.00"),
            "mid_price": Decimal("92100.75"),
            "spread": Decimal("0.50"),
            "spread_percent": Decimal("0.00054288"),
            "bid_contracts": 15,
            "ask_contracts": 20,
            "bid_btc": Decimal("0.015"),
            "ask_btc": Decimal("0.020"),
            "bid_notional_usd": Decimal("1381.5075"),
            "ask_notional_usd": Decimal("1842.02"),
            "imbalance": Decimal("-0.142857"),
        }

        self.sample_slippage = {
            "buy": {
                "order_type": "taker",
                "requested_usd": Decimal("1000.00"),
                "executed_contracts": 10,
                "executed_btc": Decimal("0.010"),
                "executed_notional_usd": Decimal("921.01"),
                "average_execution_price": Decimal("92101.00"),
                "best_price": Decimal("92101.00"),
                "slippage_usd": Decimal("0.00"),
                "slippage_percent": Decimal("0.00"),
                "taker_fee_usd": Decimal("0.460505"),
                "unfilled_usd": Decimal("78.99"),
                "fully_executed": False,
                "levels_used": 1,
                "queue_depth_ahead": None,
            }
        }

    def tearDown(self):
        if self.storage:
            self.storage.close()
        self.temp_dir.cleanup()

    def test_pragmas_enabled(self):
        cursor = self.storage._conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0].lower()
        cursor.execute("PRAGMA synchronous;")
        synchronous = cursor.fetchone()[0]

        self.assertEqual(journal_mode, "wal")
        # In SQLite, NORMAL synchronous is represented as 1
        self.assertEqual(synchronous, 1)

    def test_lossless_decimal_roundtrip(self):
        timestamp_us = 1731575000123456
        self.storage.write_snapshot_and_metrics(
            symbol="BTCUSD",
            orderbook=self.sample_orderbook,
            metrics=self.sample_metrics,
            slippage_results=self.sample_slippage,
            exchange_timestamp=1731575000000000,
            timestamp_utc="2026-11-14T09:16:40.123456+00:00",
            timestamp_us=timestamp_us,
            rtt_latency_ns=4523000
        )
        self.storage.flush()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT best_bid, best_ask, mid_price, spread, imbalance, rtt_latency_ns FROM l2_snapshots WHERE timestamp_us = ?;", (timestamp_us,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)

        # Confirm values are stored as strings and round-trip into exact Decimals
        self.assertEqual(Decimal(row[0]), Decimal("92100.50"))
        self.assertEqual(Decimal(row[1]), Decimal("92101.00"))
        self.assertEqual(Decimal(row[2]), Decimal("92100.75"))
        self.assertEqual(Decimal(row[3]), Decimal("0.50"))
        self.assertEqual(Decimal(row[4]), Decimal("-0.142857"))
        self.assertEqual(row[5], 4523000)

        cursor.execute("SELECT executed_notional_usd, unfilled_usd, fee_usd FROM execution_simulations WHERE timestamp_us = ?;", (timestamp_us,))
        sim_row = cursor.fetchone()
        self.assertIsNotNone(sim_row)
        self.assertEqual(Decimal(sim_row[0]), Decimal("921.01"))
        self.assertEqual(Decimal(sim_row[1]), Decimal("78.99"))
        self.assertEqual(Decimal(sim_row[2]), Decimal("0.460505"))
        conn.close()

    def test_idempotent_primary_key(self):
        timestamp_us = 1731575000999999
        # First write
        self.storage.write_snapshot_and_metrics(
            symbol="BTCUSD",
            orderbook=self.sample_orderbook,
            metrics=self.sample_metrics,
            timestamp_us=timestamp_us
        )
        self.storage.flush()

        # Duplicate write with same (symbol, timestamp_us)
        self.storage.write_snapshot_and_metrics(
            symbol="BTCUSD",
            orderbook=self.sample_orderbook,
            metrics=self.sample_metrics,
            timestamp_us=timestamp_us
        )
        self.storage.flush()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM l2_snapshots WHERE timestamp_us = ?;", (timestamp_us,))
        count = cursor.fetchone()[0]
        conn.close()
        # Should remain 1 due to INSERT OR IGNORE
        self.assertEqual(count, 1)

    def test_buffering_and_auto_flush(self):
        # batch_size is 2. Writing 1 should keep in buffer
        self.storage.write_snapshot_and_metrics(
            symbol="BTCUSD",
            orderbook=self.sample_orderbook,
            metrics=self.sample_metrics,
            timestamp_us=100
        )
        self.assertEqual(len(self.storage._snapshot_buffer), 1)

        # Writing second item should trigger auto-flush
        self.storage.write_snapshot_and_metrics(
            symbol="BTCUSD",
            orderbook=self.sample_orderbook,
            metrics=self.sample_metrics,
            timestamp_us=101
        )
        self.assertEqual(len(self.storage._snapshot_buffer), 0)

    def test_write_and_read_expiry_liquidity_vol(self):
        ts_us = 1794650000000000
        self.storage.write_expiry_liquidity_vol(
            underlying="BTC",
            expiry_bucket="0-DTE",
            expiry_date="141126",
            spot_price=Decimal("67400.50"),
            atm_strike=Decimal("67400.00"),
            atm_iv_mean=Decimal("0.6250"),
            straddle_premium_usd=Decimal("1250.00"),
            expected_move_pct=Decimal("1.8546"),
            total_ce_bid_lots=12000,
            total_ce_ask_lots=8500,
            total_pe_bid_lots=15000,
            total_pe_ask_lots=11000,
            lot_imbalance=Decimal("0.1600"),
            futures_rv_pct=Decimal("42.50"),
            futures_top_lots=4500,
            timestamp_utc="2026-11-14T10:00:00Z",
            timestamp_us=ts_us
        )
        self.storage.flush()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT underlying, expiry_bucket, spot_price, atm_strike, atm_iv_mean,
                   straddle_premium_usd, expected_move_pct, total_ce_bid_lots, futures_rv_pct
            FROM expiry_liquidity_vol
            WHERE timestamp_us = ?;
            """,
            (ts_us,)
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "BTC")
        self.assertEqual(row[1], "0-DTE")
        self.assertEqual(Decimal(row[2]), Decimal("67400.50"))
        self.assertEqual(Decimal(row[3]), Decimal("67400.00"))
        self.assertEqual(Decimal(row[4]), Decimal("0.6250"))
        self.assertEqual(Decimal(row[5]), Decimal("1250.00"))
        self.assertEqual(Decimal(row[6]), Decimal("1.8546"))
        self.assertEqual(row[7], 12000)
        self.assertEqual(Decimal(row[8]), Decimal("42.50"))
        conn.close()


if __name__ == "__main__":
    unittest.main()
