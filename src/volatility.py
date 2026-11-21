"""
src/volatility.py
Lot-Level Liquidity and Volatility Analytics for Delta Exchange:
- Options Volatility by Expiry (0-DTE, 1-DTE, 2-DTE): ATM Mark IV, Straddle Cost, Lot Imbalance
- Futures Rolling Realized Volatility and Spread Shock detection
"""

from collections import deque
from decimal import Decimal


class OptionsVolatilityEngine:
    """Calculates ATM IV, straddle cost, and lot-level liquidity for options by expiry bucket."""

    @staticmethod
    def _to_decimal(val, default="0") -> Decimal:
        if val is None or val == "":
            return Decimal(default)
        return Decimal(str(val))

    @classmethod
    def analyze_expiry_bucket(
        cls,
        bucket_name: str,
        expiry_meta: dict,
        spot_price: Decimal
    ) -> dict:
        """
        Analyze ATM Call/Put IV, straddle pricing, and aggregate lot liquidity
        across all ATM ± 5 strikes in the expiry bucket.
        """
        calls: list[dict] = expiry_meta.get("calls", [])
        puts: list[dict] = expiry_meta.get("puts", [])
        atm_strike: Decimal = expiry_meta.get("atm_strike", Decimal(0))
        expiry_str: str = expiry_meta.get("expiry_str", "")

        # 1. Lot-level liquidity aggregation across all strikes in bucket
        total_ce_bid_lots = 0
        total_ce_ask_lots = 0
        total_pe_bid_lots = 0
        total_pe_ask_lots = 0

        for c in calls:
            q = c.get("quotes") or {}
            total_ce_bid_lots += int(q.get("bid_size") or 0)
            total_ce_ask_lots += int(q.get("ask_size") or 0)

        for p in puts:
            q = p.get("quotes") or {}
            total_pe_bid_lots += int(q.get("bid_size") or 0)
            total_pe_ask_lots += int(q.get("ask_size") or 0)

        total_bids = total_ce_bid_lots + total_pe_bid_lots
        total_asks = total_ce_ask_lots + total_pe_ask_lots
        total_lots = total_bids + total_asks

        lot_imbalance = (
            Decimal(str(total_bids - total_asks)) / Decimal(str(total_lots))
            if total_lots > 0 else Decimal(0)
        )

        # 2. Extract ATM Call and Put instruments
        atm_calls = [
            c for c in calls
            if cls._to_decimal(c.get("strike_price")) == atm_strike
        ]
        atm_puts = [
            p for p in puts
            if cls._to_decimal(p.get("strike_price")) == atm_strike
        ]

        atm_call = atm_calls[0] if atm_calls else (calls[0] if calls else {})
        atm_put = atm_puts[0] if atm_puts else (puts[0] if puts else {})

        # Extract Mark IV
        def get_mark_iv(item: dict) -> Decimal:
            q = item.get("quotes") or {}
            iv_raw = q.get("mark_iv") or item.get("mark_iv") or item.get("mark_vol")
            return cls._to_decimal(iv_raw, "0")

        call_mark_iv = get_mark_iv(atm_call)
        put_mark_iv = get_mark_iv(atm_put)

        if call_mark_iv > 0 and put_mark_iv > 0:
            mean_atm_iv = (call_mark_iv + put_mark_iv) / Decimal(2)
        elif call_mark_iv > 0:
            mean_atm_iv = call_mark_iv
        else:
            mean_atm_iv = put_mark_iv

        # Extract Mark Prices for ATM Straddle
        call_mark_price = cls._to_decimal(
            atm_call.get("mark_price") or (atm_call.get("quotes") or {}).get("best_ask")
        )
        put_mark_price = cls._to_decimal(
            atm_put.get("mark_price") or (atm_put.get("quotes") or {}).get("best_ask")
        )

        straddle_premium_usd = call_mark_price + put_mark_price
        expected_move_pct = (
            (straddle_premium_usd / spot_price) * Decimal(100)
            if spot_price > 0 else Decimal(0)
        )

        return {
            "expiry_bucket": bucket_name,
            "expiry_date": expiry_str,
            "atm_strike": atm_strike,
            "call_mark_iv": call_mark_iv,
            "put_mark_iv": put_mark_iv,
            "mean_atm_iv": mean_atm_iv,
            "atm_call_price": call_mark_price,
            "atm_put_price": put_mark_price,
            "straddle_premium_usd": straddle_premium_usd,
            "expected_move_pct": expected_move_pct,
            "total_ce_bid_lots": total_ce_bid_lots,
            "total_ce_ask_lots": total_ce_ask_lots,
            "total_pe_bid_lots": total_pe_bid_lots,
            "total_pe_ask_lots": total_pe_ask_lots,
            "total_bid_lots": total_bids,
            "total_ask_lots": total_asks,
            "lot_imbalance": lot_imbalance,
        }


class RollingRealizedVolatility:
    """
    Computes rolling tick-to-tick Realized Volatility and spread shock metrics
    using Decimal arithmetic exclusively.
    """

    def __init__(self, window_size: int = 60, annualization_factor: Decimal = Decimal("5615.69")):
        self.window_size = max(5, window_size)
        self.annualization_factor = annualization_factor
        self.price_history: deque = deque(maxlen=self.window_size)
        self.spread_history: deque = deque(maxlen=self.window_size)

    def update(self, mid_price: Decimal, spread: Decimal) -> dict:
        """Record new mid price and spread, returning updated volatility analytics."""
        self.price_history.append(mid_price)
        self.spread_history.append(spread)

        n = len(self.price_history)
        if n < 2:
            return {
                "rv_sample_count": n,
                "rv_intraday_pct": Decimal(0),
                "rv_annualized_pct": Decimal(0),
                "avg_spread": spread,
                "spread_expansion_ratio": Decimal("1.0"),
                "spread_shock": False,
            }

        # Calculate discrete returns
        returns = []
        for i in range(1, n):
            p_prev = self.price_history[i - 1]
            p_curr = self.price_history[i]
            if p_prev > 0:
                ret = (p_curr - p_prev) / p_prev
                returns.append(ret)

        if not returns:
            return {
                "rv_sample_count": n,
                "rv_intraday_pct": Decimal(0),
                "rv_annualized_pct": Decimal(0),
                "avg_spread": spread,
                "spread_expansion_ratio": Decimal("1.0"),
                "spread_shock": False,
            }

        num_returns = Decimal(str(len(returns)))
        mean_ret = sum(returns) / num_returns

        variance = sum((r - mean_ret) ** 2 for r in returns) / (num_returns if num_returns == 1 else (num_returns - Decimal(1)))
        std_dev = variance.sqrt()

        rv_intraday_pct = std_dev * Decimal(100)
        rv_annualized_pct = rv_intraday_pct * self.annualization_factor

        # Spread shock calculation
        avg_spread = sum(self.spread_history) / Decimal(str(len(self.spread_history)))
        expansion_ratio = (spread / avg_spread) if avg_spread > 0 else Decimal("1.0")
        spread_shock = expansion_ratio >= Decimal("2.0")

        return {
            "rv_sample_count": n,
            "rv_intraday_pct": rv_intraday_pct,
            "rv_annualized_pct": rv_annualized_pct,
            "avg_spread": avg_spread,
            "spread_expansion_ratio": expansion_ratio,
            "spread_shock": spread_shock,
        }
