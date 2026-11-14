"""
src/instruments.py
Dynamic discovery and classification of Delta Exchange India instruments:
- Perpetual Futures (BTCUSD, ETHUSD)
- 0-DTE, 1-DTE, and 2-DTE Options (Calls & Puts)
- ATM ± 5 strikes filtering aligned with 12:00 UTC (17:30 IST) settlement
"""

import json
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple


class InstrumentDiscovery:
    """Dynamic instrument discovery and option strike filtering engine."""

    BASE_URL = "https://api.india.delta.exchange"
    SETTLEMENT_HOUR_UTC = 12  # Delta Exchange options settle daily at 12:00 UTC (17:30 IST)

    def __init__(self, base_url: str = BASE_URL, timeout: int = 10):
        self.base_url = base_url
        self.timeout = timeout

    def fetch_tickers(self) -> List[dict]:
        """Fetch all active market tickers via Delta bulk snapshot endpoint."""
        url = f"{self.base_url}/v2/tickers"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Delta-Liquidity-Monitor/2.0",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"Unexpected HTTP status: {response.status}")
                raw_data = response.read()
                data = json.loads(raw_data.decode("utf-8"))
                if not data.get("success", False):
                    raise RuntimeError(f"Delta API error: {data}")
                return data.get("result", [])
        except urllib.error.URLError as error:
            raise RuntimeError(f"Failed to fetch tickers: {error.reason}") from error

    @staticmethod
    def parse_expiry_date(symbol: str) -> Optional[date]:
        """
        Extract expiry date from option symbol.
        Format: {C|P}-{UNDERLYING}-{STRIKE}-{DDMMYY}
        e.g. C-BTC-99000-141126 -> date(2026, 11, 14)
        """
        parts = symbol.split("-")
        if len(parts) < 4:
            return None
        date_str = parts[-1]
        if len(date_str) != 6 or not date_str.isdigit():
            return None
        try:
            day = int(date_str[0:2])
            month = int(date_str[2:4])
            year = 2000 + int(date_str[4:6])
            return date(year, month, day)
        except ValueError:
            return None

    @classmethod
    def classify_dte(
        cls,
        expiry_date: date,
        current_utc: Optional[datetime] = None
    ) -> Optional[str]:
        """
        Classify option into '0-DTE', '1-DTE', or '2-DTE' based on 12:00 UTC settlement.
        Options settled in the past return None.
        """
        now = current_utc or datetime.now(timezone.utc)
        settlement_dt = datetime.combine(
            expiry_date,
            time(cls.SETTLEMENT_HOUR_UTC, 0, tzinfo=timezone.utc)
        )

        if settlement_dt <= now:
            return None  # Already expired or currently in settlement

        # Target settlement dates for 0-DTE, 1-DTE, 2-DTE
        # If current time is before 12:00 UTC, today's 12:00 UTC is 0-DTE
        if now.time() < time(cls.SETTLEMENT_HOUR_UTC, 0):
            d0 = now.date()
            d1 = now.date() + timedelta(days=1)
            d2 = now.date() + timedelta(days=2)
        else:
            # After 12:00 UTC, today's settlement has passed; tomorrow is 0-DTE
            d0 = now.date() + timedelta(days=1)
            d1 = now.date() + timedelta(days=2)
            d2 = now.date() + timedelta(days=3)

        if expiry_date == d0:
            return "0-DTE"
        elif expiry_date == d1:
            return "1-DTE"
        elif expiry_date == d2:
            return "2-DTE"
        return None

    @staticmethod
    def filter_atm_strikes(
        options_list: List[dict],
        spot_price: Decimal,
        num_strikes_each_side: int = 5
    ) -> Tuple[Decimal, List[Decimal], List[dict]]:
        """
        Find ATM strike closest to spot_price and select ATM ± num_strikes_each_side.
        Returns: (atm_strike, selected_strikes_list, filtered_options_list)
        """
        if not options_list:
            return Decimal("0"), [], []

        unique_strikes: List[Decimal] = sorted(
            set(Decimal(str(item["strike_price"])) for item in options_list if item.get("strike_price"))
        )

        if not unique_strikes:
            return Decimal("0"), [], []

        atm_strike = min(unique_strikes, key=lambda s: abs(s - spot_price))
        atm_idx = unique_strikes.index(atm_strike)

        start_idx = max(0, atm_idx - num_strikes_each_side)
        end_idx = min(len(unique_strikes), atm_idx + num_strikes_each_side + 1)
        selected_strikes: List[Decimal] = unique_strikes[start_idx:end_idx]

        selected_set: Set[Decimal] = set(selected_strikes)
        filtered_options = [
            opt for opt in options_list
            if Decimal(str(opt.get("strike_price", 0))) in selected_set
        ]

        return atm_strike, selected_strikes, filtered_options

    def discover_instruments(
        self,
        tickers: Optional[List[dict]] = None,
        underlyings: Tuple[str, ...] = ("BTC", "ETH"),
        current_utc: Optional[datetime] = None,
        num_strikes: int = 5,
    ) -> Dict[str, dict]:
        """
        Discover active Perpetuals and ATM ± num_strikes for 0-DTE, 1-DTE, 2-DTE options.
        """
        if tickers is None:
            tickers = self.fetch_tickers()

        result = {}

        for asset in underlyings:
            perp_symbol = f"{asset}USD"
            perp_candidates = [
                t for t in tickers
                if t.get("symbol") == perp_symbol and t.get("contract_type") == "perpetual_futures"
            ]

            if not perp_candidates:
                continue

            perp_ticker = perp_candidates[0]
            spot_price_raw = perp_ticker.get("spot_price") or perp_ticker.get("mark_price")
            if not spot_price_raw:
                continue
            spot_price = Decimal(str(spot_price_raw))

            # Group options by classified DTE bucket
            buckets: Dict[str, List[dict]] = {"0-DTE": [], "1-DTE": [], "2-DTE": []}

            asset_options = [
                t for t in tickers
                if t.get("contract_type") in ("call_options", "put_options")
                and (
                    t.get("underlying_asset_symbol") == asset
                    or f"-{asset}-" in t.get("symbol", "")
                )
            ]

            for opt in asset_options:
                symbol = opt.get("symbol", "")
                expiry_d = self.parse_expiry_date(symbol)
                if not expiry_d:
                    continue
                bucket = self.classify_dte(expiry_d, current_utc=current_utc)
                if bucket in buckets:
                    buckets[bucket].append(opt)

            expiries_meta = {}
            for bucket_name, opts in buckets.items():
                if not opts:
                    continue

                atm_strike, selected_strikes, filtered_opts = self.filter_atm_strikes(
                    opts, spot_price=spot_price, num_strikes_each_side=num_strikes
                )

                calls = [
                    o for o in filtered_opts
                    if o.get("contract_type") == "call_options"
                ]
                puts = [
                    o for o in filtered_opts
                    if o.get("contract_type") == "put_options"
                ]

                # Identify expiry date string (DDMMYY) from first option in bucket
                first_sym = opts[0].get("symbol", "")
                expiry_str = first_sym.split("-")[-1] if "-" in first_sym else ""

                expiries_meta[bucket_name] = {
                    "expiry_str": expiry_str,
                    "atm_strike": atm_strike,
                    "selected_strikes": selected_strikes,
                    "calls": calls,
                    "puts": puts,
                    "total_instruments": len(calls) + len(puts),
                }

            result[asset] = {
                "underlying": asset,
                "spot_price": spot_price,
                "perpetual": perp_ticker,
                "expiries": expiries_meta,
            }

        return result
