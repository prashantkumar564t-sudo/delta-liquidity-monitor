import unittest
from decimal import Decimal

from src.volatility import OptionsVolatilityEngine, RollingRealizedVolatility


class TestVolatilityEngine(unittest.TestCase):
    """Test suite for Options Volatility (IV, straddle) and Futures Realized Volatility."""

    def test_options_volatility_analysis(self):
        spot = Decimal("67000.00")
        expiry_meta = {
            "expiry_str": "141126",
            "atm_strike": Decimal("67000"),
            "calls": [
                {
                    "symbol": "C-BTC-67000-141126",
                    "strike_price": "67000",
                    "mark_price": "650.00",
                    "quotes": {
                        "mark_iv": "0.6200",
                        "bid_size": "100",
                        "ask_size": "150",
                    },
                },
                {
                    "symbol": "C-BTC-68000-141126",
                    "strike_price": "68000",
                    "mark_price": "300.00",
                    "quotes": {
                        "mark_iv": "0.6400",
                        "bid_size": "50",
                        "ask_size": "80",
                    },
                },
            ],
            "puts": [
                {
                    "symbol": "P-BTC-67000-141126",
                    "strike_price": "67000",
                    "mark_price": "630.00",
                    "quotes": {
                        "mark_iv": "0.5800",
                        "bid_size": "200",
                        "ask_size": "120",
                    },
                },
            ],
        }

        res = OptionsVolatilityEngine.analyze_expiry_bucket("0-DTE", expiry_meta, spot_price=spot)

        self.assertEqual(res["expiry_bucket"], "0-DTE")
        self.assertEqual(res["atm_strike"], Decimal("67000"))
        self.assertEqual(res["call_mark_iv"], Decimal("0.6200"))
        self.assertEqual(res["put_mark_iv"], Decimal("0.5800"))
        # Mean IV = (0.62 + 0.58) / 2 = 0.60
        self.assertEqual(res["mean_atm_iv"], Decimal("0.6000"))

        # Straddle = 650 + 630 = 1280
        self.assertEqual(res["straddle_premium_usd"], Decimal("1280.00"))
        expected_move = (Decimal("1280.00") / spot) * Decimal("100")
        self.assertEqual(res["expected_move_pct"], expected_move)

        # Lots: CE bids: 100+50=150, CE asks: 150+80=230, PE bids: 200, PE asks: 120
        self.assertEqual(res["total_ce_bid_lots"], 150)
        self.assertEqual(res["total_ce_ask_lots"], 230)
        self.assertEqual(res["total_pe_bid_lots"], 200)
        self.assertEqual(res["total_pe_ask_lots"], 120)
        # Total bids = 350, Total asks = 350 -> imbalance = 0
        self.assertEqual(res["lot_imbalance"], Decimal("0"))

    def test_rolling_realized_volatility_and_shock(self):
        engine = RollingRealizedVolatility(window_size=10)

        # Feed steady prices with $0.50 spread
        for p in [100, 100.1, 99.9, 100.0, 100.2, 100.0]:
            metrics = engine.update(mid_price=Decimal(str(p)), spread=Decimal("0.50"))

        self.assertGreater(metrics["rv_intraday_pct"], Decimal("0"))
        self.assertGreater(metrics["rv_annualized_pct"], Decimal("0"))
        self.assertFalse(metrics["spread_shock"])

        # Feed a spread shock (spread expands to $1.50, > 2x average $0.50)
        shock_metrics = engine.update(mid_price=Decimal("100.0"), spread=Decimal("1.50"))
        self.assertTrue(shock_metrics["spread_shock"])
        self.assertGreaterEqual(shock_metrics["spread_expansion_ratio"], Decimal("2.0"))


if __name__ == "__main__":
    unittest.main()
