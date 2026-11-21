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
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal


class InstrumentDiscovery:
    """Dynamic instrument discovery and option strike filtering engine."""

    BASE_URL = "https://api.india.delta.exchange"
    SETTLEMENT_HOUR_UTC = 12  # Delta Exchange options settle daily at 12:00 UTC (17:30 IST)

    def __init__(self, base_url: str = BASE_URL, timeout: int = 10):
        self.base_url = base_url
        self.timeout = timeout

    def fetch_tickers(self) -> list[dict]:
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
    def parse_expiry_date(symbol: str) -> date | None:
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
        current_utc: datetime | None = None
    ) -> str | None:
        """
        Classify option into '0-DTE', '1-DTE', or '2-DTE' based on 12:00 UTC settlement.
        Options settled in the past return None.
        """
        now = current_utc or datetime.now(UTC)
        settlement_dt = datetime.combine(
            expiry_date,
            time(cls.SETTLEMENT_HOUR_UTC, 0, tzinfo=UTC)
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
        options_list: list[dict],
        spot_price: Decimal,
        num_strikes_each_side: int = 5
    ) -> tuple[Decimal, list[Decimal], list[dict]]:
        """
        Find ATM strike closest to spot_price and select ATM ± num_strikes_each_side.
        Returns: (atm_strike, selected_strikes_list, filtered_options_list)
        """
        if not options_list:
            return Decimal(0), [], []

        unique_strikes: list[Decimal] = sorted(
            {Decimal(str(item["strike_price"])) for item in options_list if item.get("strike_price")}
        )

        if not unique_strikes:
            return Decimal(0), [], []

        atm_strike = min(unique_strikes, key=lambda s: abs(s - spot_price))
        atm_idx = unique_strikes.index(atm_strike)

        start_idx = max(0, atm_idx - num_strikes_each_side)
        end_idx = min(len(unique_strikes), atm_idx + num_strikes_each_side + 1)
        selected_strikes: list[Decimal] = unique_strikes[start_idx:end_idx]

        selected_set: set[Decimal] = set(selected_strikes)
        filtered_options = [
            opt for opt in options_list
            if Decimal(str(opt.get("strike_price", 0))) in selected_set
        ]

        return atm_strike, selected_strikes, filtered_options

    def discover_instruments(
        self,
        tickers: list[dict] | None = None,
        underlyings: tuple[str, ...] = ("BTC", "ETH"),
        current_utc: datetime | None = None,
        num_strikes: int = 5,
    ) -> dict[str, dict]:
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
            buckets: dict[str, list[dict]] = {"0-DTE": [], "1-DTE": [], "2-DTE": []}

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

    def discover_otm_options(
        self,
        underlyings: tuple[str, ...] = ("BTC", "ETH", "PAXG", "XAUT"),
        min_delta: float = 0.07,
        max_delta: float = 0.25,
        current_utc: datetime | None = None,
    ) -> list[dict]:
        """Convenience method delegating to module-level discover_otm_options."""
        return discover_otm_options(
            client=self,
            underlyings=underlyings,
            min_delta=min_delta,
            max_delta=max_delta,
            current_utc=current_utc,
        )


def discover_otm_options(
    client=None,
    underlyings: tuple[str, ...] = ("BTC", "ETH", "PAXG", "XAUT"),
    min_delta: float = 0.05,
    max_delta: float = 0.35,
    current_utc: datetime | None = None,
) -> list[dict]:
    """
    Discover live 0-DTE and 1-DTE OTM call and put options within delta range [min_delta, max_delta].
    
    Accepts client as InstrumentDiscovery, DeltaAPI, list of tickers, or None.
    Calculates mark-relative spread and bid slippage metrics for empirical liquidity auditing.
    """
    if client is None:
        discovery = InstrumentDiscovery()
        tickers = discovery.fetch_tickers()
    elif isinstance(client, list):
        tickers = client
        discovery = InstrumentDiscovery()
    elif hasattr(client, "fetch_tickers"):
        discovery = client
        tickers = client.fetch_tickers()
    elif hasattr(client, "_get"):
        discovery = InstrumentDiscovery(base_url=getattr(client, "BASE_URL", InstrumentDiscovery.BASE_URL))
        tickers = client._get("/v2/tickers") or []
    else:
        discovery = InstrumentDiscovery()
        tickers = []

    underlying_targets = [u.strip().upper() for u in underlyings if u.strip()]
    target_set = set(underlying_targets)
    # Recognize precious metal aliases (PAXG / XAUT / GOLD) interchangeably
    if any(g in target_set for g in ("PAXG", "XAUT", "GOLD")):
        target_set.update({"PAXG", "XAUT", "GOLD"})

    results = []

    for t in tickers:
        ctype = t.get("contract_type", "")
        sym = t.get("symbol", "")

        # Check if option contract
        if ctype not in ("call_options", "put_options") and not (sym.startswith(("C-", "P-"))):
            continue

        # Match underlying asset
        u_raw = (t.get("underlying_asset_symbol") or "").upper()
        matched_u = None
        if u_raw in target_set:
            matched_u = u_raw
        else:
            for u in target_set:
                if f"-{u}-" in sym:
                    matched_u = u
                    break

        if not matched_u:
            continue

        # Parse expiry and classify DTE (0-DTE / 1-DTE)
        exp_d = discovery.parse_expiry_date(sym)
        if not exp_d:
            continue

        bucket = discovery.classify_dte(exp_d, current_utc=current_utc)
        if bucket not in ("0-DTE", "1-DTE"):
            continue

        # Extract delta from greeks
        greeks = t.get("greeks") or {}
        delta_val = greeks.get("delta")
        if delta_val is None:
            continue
        try:
            delta = float(delta_val)
        except (ValueError, TypeError):
            continue

        abs_delta = abs(delta)
        if not (float(min_delta) <= abs_delta <= float(max_delta)):
            continue

        quotes = t.get("quotes") or {}

        # Strike price
        strike_raw = t.get("strike_price")
        try:
            strike = float(strike_raw) if strike_raw is not None else 0.0
        except (ValueError, TypeError):
            strike = 0.0

        # Mark price
        mark_price_raw = t.get("mark_price")
        try:
            mark_price = float(mark_price_raw) if mark_price_raw is not None else 0.0
        except (ValueError, TypeError):
            mark_price = 0.0

        # LTP (close or last_price)
        close_raw = t.get("close") or t.get("last_price")
        try:
            ltp = float(close_raw) if close_raw is not None else None
        except (ValueError, TypeError):
            ltp = None

        # Best bid / ask
        try:
            best_bid = float(quotes.get("best_bid")) if quotes.get("best_bid") not in (None, "") else 0.0
        except (ValueError, TypeError):
            best_bid = 0.0

        try:
            best_ask = float(quotes.get("best_ask")) if quotes.get("best_ask") not in (None, "") else 0.0
        except (ValueError, TypeError):
            best_ask = 0.0

        # Bid / ask size
        try:
            bid_size = float(quotes.get("bid_size")) if quotes.get("bid_size") not in (None, "") else 0.0
        except (ValueError, TypeError):
            bid_size = 0.0

        try:
            ask_size = float(quotes.get("ask_size")) if quotes.get("ask_size") not in (None, "") else 0.0
        except (ValueError, TypeError):
            ask_size = 0.0

        # Implied Volatility
        iv_raw = quotes.get("mark_iv") or t.get("mark_iv") or quotes.get("ask_iv") or quotes.get("bid_iv")
        try:
            iv = float(iv_raw) if iv_raw not in (None, "") else None
        except (ValueError, TypeError):
            iv = None

        # Option type
        if ctype == "call_options" or sym.startswith("C-"):
            option_type = "CE"
        elif ctype == "put_options" or sym.startswith("P-"):
            option_type = "PE"
        else:
            option_type = "UNKNOWN"

        # Microstructure divergence formulas
        if mark_price > 0:
            spread_vs_mark_pct = ((best_ask - best_bid) / mark_price) * 100.0
            bid_slippage_pct = ((mark_price - best_bid) / mark_price) * 100.0
        else:
            spread_vs_mark_pct = 0.0
            bid_slippage_pct = 0.0

        record = {
            "underlying": matched_u,
            "symbol": sym,
            "expiry_bucket": bucket,
            "expiry_date": exp_d.isoformat(),
            "option_type": option_type,
            "strike": strike,
            "delta": delta,
            "abs_delta": abs_delta,
            "iv": iv,
            "mark_price": mark_price,
            "ltp": ltp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "spread_vs_mark_pct": spread_vs_mark_pct,
            "bid_slippage_pct": bid_slippage_pct,
            "raw_ticker": t,
        }
        results.append(record)

    return results
