import unittest
from datetime import date, datetime, time, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from src.instruments import InstrumentDiscovery


class TestInstrumentDiscovery(unittest.TestCase):
    """Test suite for dynamic multi-instrument discovery and option strike filtering."""

    def setUp(self):
        self.discovery = InstrumentDiscovery()

    def test_parse_expiry_date(self):
        self.assertEqual(
            self.discovery.parse_expiry_date("C-BTC-99000-141126"),
            date(2026, 11, 14)
        )
        self.assertEqual(
            self.discovery.parse_expiry_date("P-ETH-3400-290127"),
            date(2027, 1, 29)
        )
        self.assertIsNone(self.discovery.parse_expiry_date("BTCUSD"))
        self.assertIsNone(self.discovery.parse_expiry_date("C-BTC-INVALID"))

    def test_classify_dte_before_12_utc(self):
        # 14 Nov 2026 10:00 UTC (before 12:00 UTC settlement)
        now = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)

        self.assertEqual(self.discovery.classify_dte(date(2026, 11, 14), current_utc=now), "0-DTE")
        self.assertEqual(self.discovery.classify_dte(date(2026, 11, 15), current_utc=now), "1-DTE")
        self.assertEqual(self.discovery.classify_dte(date(2026, 11, 16), current_utc=now), "2-DTE")
        self.assertIsNone(self.discovery.classify_dte(date(2026, 11, 17), current_utc=now))
        # Past date
        self.assertIsNone(self.discovery.classify_dte(date(2026, 11, 13), current_utc=now))

    def test_classify_dte_after_12_utc(self):
        # 14 Nov 2026 13:00 UTC (after 12:00 UTC settlement)
        now = datetime(2026, 11, 14, 13, 0, tzinfo=timezone.utc)

        # 14 Nov option already expired at 12:00 UTC
        self.assertIsNone(self.discovery.classify_dte(date(2026, 11, 14), current_utc=now))
        # 15 Nov is now the next 0-DTE
        self.assertEqual(self.discovery.classify_dte(date(2026, 11, 15), current_utc=now), "0-DTE")
        self.assertEqual(self.discovery.classify_dte(date(2026, 11, 16), current_utc=now), "1-DTE")
        self.assertEqual(self.discovery.classify_dte(date(2026, 11, 17), current_utc=now), "2-DTE")

    def test_filter_atm_strikes(self):
        strikes = [
            Decimal(str(p))
            for p in [64000, 65000, 66000, 67000, 68000, 69000, 70000, 71000, 72000, 73000, 74000]
        ]
        options = [{"strike_price": str(s), "symbol": f"C-BTC-{s}-141126"} for s in strikes]
        spot = Decimal("68100.50")

        atm_strike, selected, filtered = self.discovery.filter_atm_strikes(
            options, spot_price=spot, num_strikes_each_side=2
        )

        # 68000 is closest to 68100.50
        self.assertEqual(atm_strike, Decimal("68000"))
        # 2 strikes below, ATM, 2 strikes above = [66000, 67000, 68000, 69000, 70000]
        self.assertEqual(
            selected,
            [Decimal("66000"), Decimal("67000"), Decimal("68000"), Decimal("69000"), Decimal("70000")]
        )
        self.assertEqual(len(filtered), 5)

    def test_discover_instruments_mocked(self):
        now = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
        fake_tickers = [
            {
                "symbol": "BTCUSD",
                "contract_type": "perpetual_futures",
                "spot_price": "67000.0",
                "quotes": {"best_bid": "66999.5", "best_ask": "67000.0"}
            },
            {
                "symbol": "ETHUSD",
                "contract_type": "perpetual_futures",
                "spot_price": "3100.0",
                "quotes": {"best_bid": "3099.5", "best_ask": "3100.0"}
            },
            # BTC Options 0-DTE (141126)
            {
                "symbol": "C-BTC-67000-141126",
                "underlying_asset_symbol": "BTC",
                "contract_type": "call_options",
                "strike_price": "67000",
                "quotes": {"best_bid": "500", "best_ask": "520"}
            },
            {
                "symbol": "P-BTC-67000-141126",
                "underlying_asset_symbol": "BTC",
                "contract_type": "put_options",
                "strike_price": "67000",
                "quotes": {"best_bid": "490", "best_ask": "510"}
            },
        ]

        result = self.discovery.discover_instruments(
            tickers=fake_tickers,
            underlyings=("BTC", "ETH"),
            current_utc=now,
            num_strikes=2
        )

        self.assertIn("BTC", result)
        self.assertIn("ETH", result)

        btc_res = result["BTC"]
        self.assertEqual(btc_res["spot_price"], Decimal("67000.0"))
        self.assertIn("0-DTE", btc_res["expiries"])

        dte0 = btc_res["expiries"]["0-DTE"]
        self.assertEqual(dte0["atm_strike"], Decimal("67000"))
        self.assertEqual(len(dte0["calls"]), 1)
        self.assertEqual(len(dte0["puts"]), 1)


if __name__ == "__main__":
    unittest.main()
