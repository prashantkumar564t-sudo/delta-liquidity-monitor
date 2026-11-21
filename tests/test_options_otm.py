import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from src.instruments import discover_otm_options
from src.storage import SQLiteStorage


class TestOptionsOTM(unittest.TestCase):
    """Test suite for Options OTM Liquidity discovery and SQLite WAL persistence."""

    def setUp(self):
        self.ref_utc = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
        # Expiries relative to ref_utc: 141126 is 0-DTE, 151126 is 1-DTE, 161126 is 2-DTE
        self.mock_tickers = [
            # 1. BTC 0-DTE OTM Call (Delta 0.12) -> MATCH
            {
                "symbol": "C-BTC-95000-141126",
                "contract_type": "call_options",
                "underlying_asset_symbol": "BTC",
                "strike_price": "95000",
                "mark_price": "100.0",
                "close": "98.0",
                "quotes": {
                    "best_bid": "95.0",
                    "best_ask": "105.0",
                    "bid_size": "250",
                    "ask_size": "300",
                    "mark_iv": "0.55"
                },
                "greeks": {"delta": "0.12"}
            },
            # 2. BTC 0-DTE Deep OTM Call (Delta 0.04) -> EXCLUDED (below 0.07)
            {
                "symbol": "C-BTC-110000-141126",
                "contract_type": "call_options",
                "underlying_asset_symbol": "BTC",
                "strike_price": "110000",
                "mark_price": "10.0",
                "quotes": {"best_bid": "8.0", "best_ask": "12.0"},
                "greeks": {"delta": "0.04"}
            },
            # 3. BTC 0-DTE ITM Call (Delta 0.85) -> EXCLUDED (above 0.25)
            {
                "symbol": "C-BTC-60000-141126",
                "contract_type": "call_options",
                "underlying_asset_symbol": "BTC",
                "strike_price": "60000",
                "mark_price": "7000.0",
                "quotes": {"best_bid": "6950.0", "best_ask": "7050.0"},
                "greeks": {"delta": "0.85"}
            },
            # 4. ETH 1-DTE OTM Put (Delta -0.18) -> MATCH
            {
                "symbol": "P-ETH-2800-151126",
                "contract_type": "put_options",
                "underlying_asset_symbol": "ETH",
                "strike_price": "2800",
                "mark_price": "25.0",
                "close": "24.5",
                "quotes": {
                    "best_bid": "23.0",
                    "best_ask": "27.0",
                    "bid_size": "500",
                    "ask_size": "450",
                    "mark_iv": "0.62"
                },
                "greeks": {"delta": "-0.18"}
            },
            # 5. ETH 2-DTE OTM Put (Delta -0.15) -> EXCLUDED (2-DTE, not 0/1-DTE)
            {
                "symbol": "P-ETH-2700-161126",
                "contract_type": "put_options",
                "underlying_asset_symbol": "ETH",
                "strike_price": "2700",
                "mark_price": "30.0",
                "quotes": {"best_bid": "28.0", "best_ask": "32.0"},
                "greeks": {"delta": "-0.15"}
            },
            # 6. XAUT (Gold) 0-DTE OTM Call (Delta 0.15) -> MATCH (Gold alias)
            {
                "symbol": "C-XAUT-3900-141126",
                "contract_type": "call_options",
                "underlying_asset_symbol": "XAUT",
                "strike_price": "3900",
                "mark_price": "5.0",
                "close": "4.9",
                "quotes": {
                    "best_bid": "4.5",
                    "best_ask": "5.5",
                    "bid_size": "100",
                    "ask_size": "120",
                    "mark_iv": "0.22"
                },
                "greeks": {"delta": "0.15"}
            },
            # 7. Zero mark price edge case
            {
                "symbol": "P-BTC-50000-141126",
                "contract_type": "put_options",
                "underlying_asset_symbol": "BTC",
                "strike_price": "50000",
                "mark_price": "0.0",
                "quotes": {"best_bid": "0.0", "best_ask": "0.0"},
                "greeks": {"delta": "-0.08"}
            }
        ]

    def test_discover_otm_options_filtering(self):
        results = discover_otm_options(
            client=self.mock_tickers,
            underlyings=["BTC", "ETH", "PAXG", "XAUT"],
            min_delta=0.07,
            max_delta=0.25,
            current_utc=self.ref_utc
        )

        symbols = [r["symbol"] for r in results]
        self.assertIn("C-BTC-95000-141126", symbols)
        self.assertIn("P-ETH-2800-151126", symbols)
        self.assertIn("C-XAUT-3900-141126", symbols)
        self.assertIn("P-BTC-50000-141126", symbols)

        # Excluded items
        self.assertNotIn("C-BTC-110000-141126", symbols)  # Delta too low
        self.assertNotIn("C-BTC-60000-141126", symbols)   # Delta too high
        self.assertNotIn("P-ETH-2700-161126", symbols)    # 2-DTE

    def test_math_formulas_and_edge_cases(self):
        results = discover_otm_options(
            client=self.mock_tickers,
            underlyings=["BTC"],
            min_delta=0.07,
            max_delta=0.25,
            current_utc=self.ref_utc
        )

        btc_opt = next(r for r in results if r["symbol"] == "C-BTC-95000-141126")
        self.assertEqual(btc_opt["option_type"], "CE")
        self.assertEqual(btc_opt["expiry_bucket"], "0-DTE")
        self.assertAlmostEqual(btc_opt["mark_price"], 100.0)
        self.assertAlmostEqual(btc_opt["best_bid"], 95.0)
        self.assertAlmostEqual(btc_opt["best_ask"], 105.0)

        # spread_vs_mark_pct = (105 - 95) / 100 * 100 = 10.0%
        self.assertAlmostEqual(btc_opt["spread_vs_mark_pct"], 10.0)
        # bid_slippage_pct = (100 - 95) / 100 * 100 = 5.0%
        self.assertAlmostEqual(btc_opt["bid_slippage_pct"], 5.0)

        # Zero mark price edge case: must not throw ZeroDivisionError
        zero_opt = next(r for r in results if r["symbol"] == "P-BTC-50000-141126")
        self.assertEqual(zero_opt["spread_vs_mark_pct"], 0.0)
        self.assertEqual(zero_opt["bid_slippage_pct"], 0.0)

    def test_sqlite_storage_persistence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_telemetry.db"
            storage = SQLiteStorage(db_path=db_path, batch_size=2)

            test_records = [
                {
                    "timestamp_us": 1731575000000001,
                    "datetime_ist": "2026-11-14 15:30:00",
                    "underlying": "BTC",
                    "symbol": "C-BTC-95000-141126",
                    "expiry_bucket": "0-DTE",
                    "option_type": "CE",
                    "strike": 95000.0,
                    "delta": 0.12,
                    "iv": 0.55,
                    "mark_price": 100.0,
                    "ltp": 98.0,
                    "best_bid": 95.0,
                    "best_ask": 105.0,
                    "bid_size": 250.0,
                    "ask_size": 300.0,
                    "spread_vs_mark_pct": 10.0,
                    "bid_slippage_pct": 5.0,
                },
                {
                    "timestamp_us": 1731575000000002,
                    "datetime_ist": "2026-11-14 15:30:00",
                    "underlying": "ETH",
                    "symbol": "P-ETH-2800-151126",
                    "expiry_bucket": "1-DTE",
                    "option_type": "PE",
                    "strike": 2800.0,
                    "delta": -0.18,
                    "iv": 0.62,
                    "mark_price": 25.0,
                    "ltp": 24.5,
                    "best_bid": 23.0,
                    "best_ask": 27.0,
                    "bid_size": 500.0,
                    "ask_size": 450.0,
                    "spread_vs_mark_pct": 16.0,
                    "bid_slippage_pct": 8.0,
                }
            ]

            storage.write_otm_options_liquidity(test_records)
            storage.flush()

            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM otm_options_liquidity;")
            self.assertEqual(cur.fetchone()[0], 2)

            cur.execute("""
                SELECT symbol, underlying, expiry_bucket, option_type, strike, delta, spread_vs_mark_pct, bid_slippage_pct
                FROM otm_options_liquidity WHERE symbol = 'C-BTC-95000-141126';
            """)
            row = cur.fetchone()
            self.assertEqual(row[0], "C-BTC-95000-141126")
            self.assertEqual(row[1], "BTC")
            self.assertEqual(row[2], "0-DTE")
            self.assertEqual(row[3], "CE")
            self.assertEqual(row[4], 95000.0)
            self.assertAlmostEqual(row[5], 0.12)
            self.assertAlmostEqual(row[6], 10.0)
            self.assertAlmostEqual(row[7], 5.0)

            conn.close()
            storage.close()


if __name__ == "__main__":
    unittest.main()
