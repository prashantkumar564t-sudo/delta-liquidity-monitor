import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from src.storage import SQLiteStorage, export_session_to_parquet


class TestParquetExport(unittest.TestCase):
    """Test suite for SQLite to ZSTD-compressed Parquet export via DuckDB."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_telemetry.db"
        self.export_dir = Path(self.temp_dir.name) / "exports"
        self.storage = SQLiteStorage(db_path=self.db_path)

    def tearDown(self):
        self.storage.close()
        self.temp_dir.cleanup()

    def test_export_otm_options_to_parquet(self):
        ts_us = int(datetime(2026, 11, 22, 10, 0, tzinfo=UTC).timestamp() * 1_000_000)
        dt_ist = "2026-11-22 15:30:00"
        records = [
            {
                "timestamp_us": ts_us,
                "datetime_ist": dt_ist,
                "underlying": "BTC",
                "symbol": "C-BTC-95000-221126",
                "expiry_bucket": "0-DTE",
                "option_type": "CE",
                "strike": 95000.0,
                "delta": 0.15,
                "iv": 0.55,
                "mark_price": 120.0,
                "ltp": 118.0,
                "best_bid": 115.0,
                "best_ask": 125.0,
                "bid_size": 100.0,
                "ask_size": 120.0,
                "spread_vs_mark_pct": 8.33,
                "bid_slippage_pct": 4.17,
            },
            {
                "timestamp_us": ts_us + 1000,
                "datetime_ist": dt_ist,
                "underlying": "ETH",
                "symbol": "P-ETH-2800-221126",
                "expiry_bucket": "0-DTE",
                "option_type": "PE",
                "strike": 2800.0,
                "delta": -0.18,
                "iv": 0.60,
                "mark_price": 30.0,
                "ltp": 29.5,
                "best_bid": 28.0,
                "best_ask": 32.0,
                "bid_size": 200.0,
                "ask_size": 250.0,
                "spread_vs_mark_pct": 13.33,
                "bid_slippage_pct": 6.67,
            },
        ]

        self.storage.write_otm_options_liquidity(records)
        self.storage.flush()

        ist = timezone(timedelta(hours=5, minutes=30))
        session_dt = datetime(2026, 11, 22, 17, 0, tzinfo=ist)

        meta = export_session_to_parquet(
            db_path=self.db_path,
            session_start_us=ts_us,
            export_dir=self.export_dir,
            session_dt_ist=session_dt,
            table_name="otm_options_liquidity",
        )

        self.assertTrue(Path(meta["export_path"]).exists())
        self.assertEqual(meta["row_count"], 2)
        self.assertGreater(meta["file_size_bytes"], 0)
        self.assertEqual(meta["filename"], "delta_evening_20261122_1700_IST.parquet")


if __name__ == "__main__":
    unittest.main()
