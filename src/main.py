"""
src/main.py
Main market liquidity collector and Multi-Instrument Liquidity & Volatility Scanner.
Supports:
- Multi-instrument chain scanning (BTC & ETH Perpetuals + 0-DTE, 1-DTE, 2-DTE Options)
- Single-symbol L2 WebSocket streaming with REST fallback
- Lossless SQLite WAL & CSV telemetry sinks
- Win32 & POSIX <30 MB working set memory discipline
"""

import argparse
import gc
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Ensure root directory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.delta_api import DeltaAPI
from src.delta_ws import DeltaWebSocketClient
from src.instruments import InstrumentDiscovery
from src.orderbook import OrderBookAnalyzer
from src.slippage import SlippageCalculator
from src.storage import CSVStorage, SQLiteStorage
from src.volatility import OptionsVolatilityEngine, RollingRealizedVolatility


def trim_process_memory():
    """Trim unused pages from working set to maintain strict < 30 MB RAM ceiling on Windows."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
            ctypes.windll.psapi.EmptyWorkingSet.restype = wintypes.BOOL
            ctypes.windll.psapi.EmptyWorkingSet(handle)
        except Exception:
            pass


def run_chain_scanner(
    underlyings_str="BTC,ETH",
    duration=config.COLLECTION_DURATION,
    interval=config.SNAPSHOT_INTERVAL,
    sink="both",
):
    underlyings = tuple(u.strip().upper() for u in underlyings_str.split(",") if u.strip())
    scan_count = 0
    errors_count = 0

    print("=" * 70)
    print("Starting Delta Multi-Instrument Liquidity & Volatility Scanner")
    print(f"Underlyings: {', '.join(underlyings)} | Duration: {duration}s | Interval: {interval}s")
    print(f"Tracking: Perpetuals + 0-DTE, 1-DTE, 2-DTE Options (ATM ± 5 Strikes)")
    print(f"Storage Sink: {sink.upper()}")
    print("=" * 70)

    discovery = InstrumentDiscovery(timeout=config.API_TIMEOUT)
    sqlite_storage = SQLiteStorage() if sink in ("sqlite", "both") else None
    rv_engines = {asset: RollingRealizedVolatility(window_size=60) for asset in underlyings}

    trim_process_memory()
    start_time = time.monotonic()

    try:
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= duration:
                print("\n[+] Configured scan duration completed.")
                break

            loop_start = time.monotonic()
            timestamp_utc = datetime.now(timezone.utc).isoformat()
            timestamp_us = int(time.time() * 1_000_000)

            try:
                tickers = discovery.fetch_tickers()
                chain_data = discovery.discover_instruments(
                    tickers=tickers, underlyings=underlyings
                )

                summary_lines = []

                for asset in underlyings:
                    asset_info = chain_data.get(asset)
                    if not asset_info:
                        continue

                    spot_price = asset_info["spot_price"]
                    perp = asset_info["perpetual"]
                    q = perp.get("quotes") or {}
                    best_bid = Decimal(str(q.get("best_bid") or perp.get("close", spot_price)))
                    best_ask = Decimal(str(q.get("best_ask") or perp.get("close", spot_price)))
                    mid_price = (best_bid + best_ask) / Decimal("2")
                    spread = best_ask - best_bid
                    fut_bid_lots = int(q.get("bid_size") or 0)
                    fut_ask_lots = int(q.get("ask_size") or 0)
                    fut_top_lots = fut_bid_lots + fut_ask_lots

                    # Update Rolling Realized Volatility
                    rv_info = rv_engines[asset].update(mid_price, spread)
                    rv_annualized = rv_info["rv_annualized_pct"]

                    expiries = asset_info.get("expiries", {})
                    dte0 = expiries.get("0-DTE", {})
                    dte1 = expiries.get("1-DTE", {})

                    dte0_iv = "N/A"
                    dte0_move = "N/A"
                    dte1_iv = "N/A"

                    # Process each expiry bucket for persistence
                    for b_name in ("0-DTE", "1-DTE", "2-DTE"):
                        e_meta = expiries.get(b_name)
                        if not e_meta:
                            continue

                        vol_metrics = OptionsVolatilityEngine.analyze_expiry_bucket(
                            b_name, e_meta, spot_price=spot_price
                        )

                        if b_name == "0-DTE":
                            dte0_iv = f"{vol_metrics['mean_atm_iv'] * Decimal('100'):.1f}%"
                            dte0_move = f"{vol_metrics['expected_move_pct']:.2f}%"
                        elif b_name == "1-DTE":
                            dte1_iv = f"{vol_metrics['mean_atm_iv'] * Decimal('100'):.1f}%"

                        if sqlite_storage:
                            sqlite_storage.write_expiry_liquidity_vol(
                                underlying=asset,
                                expiry_bucket=b_name,
                                expiry_date=vol_metrics["expiry_date"],
                                spot_price=spot_price,
                                atm_strike=vol_metrics["atm_strike"],
                                atm_iv_mean=vol_metrics["mean_atm_iv"],
                                straddle_premium_usd=vol_metrics["straddle_premium_usd"],
                                expected_move_pct=vol_metrics["expected_move_pct"],
                                total_ce_bid_lots=vol_metrics["total_ce_bid_lots"],
                                total_ce_ask_lots=vol_metrics["total_ce_ask_lots"],
                                total_pe_bid_lots=vol_metrics["total_pe_bid_lots"],
                                total_pe_ask_lots=vol_metrics["total_pe_ask_lots"],
                                lot_imbalance=vol_metrics["lot_imbalance"],
                                futures_rv_pct=rv_annualized,
                                futures_top_lots=fut_top_lots,
                                timestamp_utc=timestamp_utc,
                                timestamp_us=timestamp_us,
                            )

                    summary_lines.append(
                        f"{asset}: ${spot_price:,.1f} | Fut Lots: B{fut_bid_lots}/A{fut_ask_lots} | "
                        f"0D-IV: {dte0_iv} (Move: {dte0_move}) | 1D-IV: {dte1_iv} | RV: {rv_annualized:.1f}%"
                    )

                scan_count += 1
                lead = f"\r[{scan_count:04d} | {int(elapsed)}s/{duration}s] "
                status_display = lead + " || ".join(summary_lines)
                sys.stdout.write(status_display)
                sys.stdout.flush()

            except Exception as err:
                errors_count += 1
                print(f"\n[!] Scanner warning: {err}")

            iteration_time = time.monotonic() - loop_start
            sleep_time = max(0.0, interval - iteration_time)
            trim_process_memory()
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[!] Scanner stopped by user.")
    finally:
        if sqlite_storage:
            sqlite_storage.close()

    print("\n" + "=" * 70)
    print("Multi-Instrument Scan Complete!")
    print(f"Total Scans: {scan_count} | Errors/Skipped: {errors_count}")
    print("=" * 70)


def run_single_collector(
    symbol=config.SYMBOL,
    budget=config.PRIMARY_SIMULATION_USD,
    duration=config.COLLECTION_DURATION,
    interval=config.SNAPSHOT_INTERVAL,
    depth=config.DEPTH,
    sink="both",
    mode="ws",
):
    snapshot_count = 0
    errors_count = 0

    print("=" * 65)
    print(f"Starting Delta Liquidity Collector: {symbol}")
    print(f"Duration: {duration}s | Interval: {interval}s | Depth: {depth}")
    print(f"Budget: ${budget:,.2f} | Storage Sink: {sink.upper()} | Ingestion: {mode.upper()}")
    print("=" * 65)

    rest_api = DeltaAPI(timeout=config.API_TIMEOUT)
    book_analyzer = OrderBookAnalyzer(contract_value=config.CONTRACT_VALUE)
    slippage_calc = SlippageCalculator(
        contract_value=config.CONTRACT_VALUE,
        taker_fee=config.TAKER_FEE,
        maker_fee=config.MAKER_FEE,
    )

    csv_storage = CSVStorage() if sink in ("csv", "both") else None
    sqlite_storage = SQLiteStorage() if sink in ("sqlite", "both") else None

    ws_client = None
    if mode == "ws":
        ws_client = DeltaWebSocketClient(
            symbol=symbol,
            ws_url=config.WS_URL,
            fallback_timeout=config.WS_TIMEOUT_SECONDS,
            rest_api=rest_api,
        )
        ws_client.start()
        time.sleep(0.5)

    trim_process_memory()
    start_time = time.monotonic()

    try:
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= duration:
                print("\n[+] Configured collection duration completed.")
                break

            loop_start = time.monotonic()
            timestamp_utc = datetime.now(timezone.utc).isoformat()
            timestamp_us = int(time.time() * 1_000_000)

            try:
                if ws_client:
                    orderbook, source = ws_client.get_orderbook(depth=depth)
                    rtt_ns = rest_api.last_rtt_ns if source == "rest_fallback" else 0
                else:
                    orderbook = rest_api.get_orderbook(symbol=symbol, depth=depth)
                    source = "rest"
                    rtt_ns = rest_api.last_rtt_ns

                if not orderbook:
                    raise RuntimeError("Empty response received from order book feed")

                metrics = book_analyzer.analyze(orderbook)

                buy_taker = slippage_calc.simulate(orderbook, order_usd=budget, side="buy")
                sell_taker = slippage_calc.simulate(orderbook, order_usd=budget, side="sell")

                buy_maker = slippage_calc.simulate_maker(
                    orderbook,
                    limit_price=metrics["best_bid"],
                    size_contracts=10,
                    side="buy"
                )
                sell_maker = slippage_calc.simulate_maker(
                    orderbook,
                    limit_price=metrics["best_ask"],
                    size_contracts=10,
                    side="sell"
                )

                slippage_results = {
                    "buy_taker": buy_taker,
                    "sell_taker": sell_taker,
                    "buy_maker": buy_maker,
                    "sell_maker": sell_maker,
                }

                if csv_storage:
                    csv_storage.write_raw_orderbook(
                        orderbook=orderbook, symbol=symbol, timestamp=timestamp_utc
                    )
                    csv_storage.write_metrics(
                        metrics=metrics,
                        slippage_results={"buy": buy_taker, "sell": sell_taker},
                        timestamp=timestamp_utc
                    )

                if sqlite_storage:
                    sqlite_storage.write_snapshot_and_metrics(
                        symbol=symbol,
                        orderbook=orderbook,
                        metrics=metrics,
                        slippage_results=slippage_results,
                        timestamp_utc=timestamp_utc,
                        timestamp_us=timestamp_us,
                        rtt_latency_ns=rtt_ns
                    )

                snapshot_count += 1
                rtt_ms_display = f"{rtt_ns / 1_000_000:.1f}ms" if rtt_ns > 0 else "WS-Live"
                sys.stdout.write(
                    f"\r[{snapshot_count:04d}] Mid: ${metrics['mid_price']:.2f} | "
                    f"Spread: ${metrics['spread']:.2f} | "
                    f"Src: {source.upper()[:7]} | RTT: {rtt_ms_display} | "
                    f"Buy Slip: {buy_taker['slippage_percent']:.4f}% | "
                    f"Elapsed: {int(elapsed)}s/{duration}s"
                )
                sys.stdout.flush()

            except Exception as err:
                errors_count += 1
                print(f"\n[!] Snapshot warning: {err}")

            iteration_time = time.monotonic() - loop_start
            sleep_time = max(0.0, interval - iteration_time)
            trim_process_memory()
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[!] Collection stopped by user.")
    finally:
        if ws_client:
            ws_client.stop()
        if sqlite_storage:
            sqlite_storage.close()

    print("\n" + "=" * 65)
    print("Collection Complete!")
    print(f"Total Snapshots: {snapshot_count} | Errors/Skipped: {errors_count}")
    print("=" * 65)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Delta Exchange Multi-Instrument Scanner & Liquidity Profiler"
    )
    parser.add_argument(
        "--mode",
        choices=["chain-scan", "ws", "rest"],
        default="chain-scan",
        help="Execution mode: chain-scan (Perps + 0/1/2-DTE Options) or ws/rest (Single Symbol)",
    )
    parser.add_argument(
        "--underlyings",
        default="BTC,ETH",
        help="Comma-separated assets for chain-scan (default: BTC,ETH)",
    )
    parser.add_argument(
        "--symbol", default=config.SYMBOL, help=f"Single-symbol tracking (default: {config.SYMBOL})"
    )
    parser.add_argument(
        "--budget", type=float, default=config.PRIMARY_SIMULATION_USD, help="Simulation budget USD"
    )
    parser.add_argument(
        "--duration", type=int, default=config.COLLECTION_DURATION, help="Run duration in seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=config.SNAPSHOT_INTERVAL, help="Polling interval in seconds"
    )
    parser.add_argument(
        "--depth", type=int, default=config.DEPTH, help="Orderbook depth levels"
    )
    parser.add_argument(
        "--sink", choices=["csv", "sqlite", "both"], default="both", help="Storage engine"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.mode == "chain-scan":
        run_chain_scanner(
            underlyings_str=args.underlyings,
            duration=args.duration,
            interval=args.interval,
            sink=args.sink,
        )
    else:
        run_single_collector(
            symbol=args.symbol,
            budget=args.budget,
            duration=args.duration,
            interval=args.interval,
            depth=args.depth,
            sink=args.sink,
            mode=args.mode,
        )
