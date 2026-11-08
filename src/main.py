"""
src/main.py
Main market liquidity collector and analyzer.
"""

import time
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.delta_api import DeltaAPI
from src.orderbook import OrderBookAnalyzer
from src.slippage import SlippageCalculator
from src.storage import CSVStorage


def run_collector(duration_seconds=config.COLLECTION_DURATION, interval=config.SNAPSHOT_INTERVAL):
    # वेरिएबल्स को शुरू में ही इनिशियलाइज़ करें
    snapshot_count = 0
    errors_count = 0

    print("=" * 60)
    print(f"Starting Delta Liquidity Collector: {config.SYMBOL}")
    print(f"Duration: {duration_seconds}s | Interval: {interval}s")
    print("=" * 60)

    try:
        api = DeltaAPI(timeout=config.API_TIMEOUT)
        book_analyzer = OrderBookAnalyzer(contract_value=config.CONTRACT_VALUE)
        slippage_calc = SlippageCalculator(
            contract_value=config.CONTRACT_VALUE,
            taker_fee=config.TAKER_FEE
        )
        storage = CSVStorage()

        start_time = time.monotonic()

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= duration_seconds:
                print("\n[+] Configured collection duration completed.")
                break

            loop_start = time.monotonic()
            timestamp_utc = datetime.now(timezone.utc).isoformat()

            try:
                orderbook = api.get_orderbook(symbol=config.SYMBOL, depth=config.DEPTH)
                if not orderbook:
                    raise RuntimeError("Empty response received from orderbook API")

                storage.write_raw_orderbook(
                    orderbook=orderbook,
                    symbol=config.SYMBOL,
                    timestamp=timestamp_utc
                )

                metrics = book_analyzer.analyze(orderbook)

                buy_slip = slippage_calc.simulate(
                    orderbook, order_usd=config.PRIMARY_SIMULATION_USD, side="buy"
                )
                sell_slip = slippage_calc.simulate(
                    orderbook, order_usd=config.PRIMARY_SIMULATION_USD, side="sell"
                )

                storage.write_metrics(
                    metrics=metrics,
                    slippage_results={"buy": buy_slip, "sell": sell_slip},
                    timestamp=timestamp_utc
                )

                snapshot_count += 1
                sys.stdout.write(
                    f"\r[{snapshot_count:04d}] Mid: ${metrics['mid_price']:.2f} | "
                    f"Spread: ${metrics['spread']:.2f} ({metrics['spread_percent']:.4f}%) | "
                    f"Buy Slip: {buy_slip['slippage_percent']:.4f}% | "
                    f"Elapsed: {int(elapsed)}s/{duration_seconds}s"
                )
                sys.stdout.flush()

            except Exception as err:
                errors_count += 1
                print(f"\n[!] Snapshot warning: {err}")

            iteration_time = time.monotonic() - loop_start
            sleep_time = max(0.0, interval - iteration_time)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[!] Collection stopped by user.")

    print("\n" + "=" * 60)
    print(f"Collection Complete!")
    print(f"Total Snapshots: {snapshot_count}")
    print(f"Errors/Skipped: {errors_count}")
    print("=" * 60)


if __name__ == "__main__":
    run_collector()