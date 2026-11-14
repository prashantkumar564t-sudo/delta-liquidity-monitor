"""
src/main.py
Main market liquidity collector and microstructure telemetry engine.
Supports WebSocket streaming with automatic REST fallback, CSV & SQLite WAL sinks,
and configurable CLI arguments.
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
from src.orderbook import OrderBookAnalyzer
from src.slippage import SlippageCalculator
from src.storage import CSVStorage, SQLiteStorage


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


def run_collector(
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
        # Brief pause to allow initial handshake
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

                # Simulate market taker orders
                buy_taker = slippage_calc.simulate(orderbook, order_usd=budget, side="buy")
                sell_taker = slippage_calc.simulate(orderbook, order_usd=budget, side="sell")

                # Simulate passive maker orders at top of book
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

                # CSV persistence
                if csv_storage:
                    csv_storage.write_raw_orderbook(
                        orderbook=orderbook,
                        symbol=symbol,
                        timestamp=timestamp_utc
                    )
                    csv_storage.write_metrics(
                        metrics=metrics,
                        slippage_results={"buy": buy_taker, "sell": sell_taker},
                        timestamp=timestamp_utc
                    )

                # SQLite WAL persistence
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
    print(f"Total Snapshots: {snapshot_count}")
    print(f"Errors/Skipped: {errors_count}")
    print("=" * 65)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Delta Exchange L2 Liquidity Monitor & Profiler"
    )
    parser.add_argument(
        "--symbol", default=config.SYMBOL, help=f"Instrument symbol (default: {config.SYMBOL})"
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
    parser.add_argument(
        "--mode", choices=["ws", "rest"], default="ws", help="Data ingestion protocol"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_collector(
        symbol=args.symbol,
        budget=args.budget,
        duration=args.duration,
        interval=args.interval,
        depth=args.depth,
        sink=args.sink,
        mode=args.mode,
    )
