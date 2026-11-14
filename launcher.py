"""
launcher.py
Launches the collector process and the RAM/Resource monitor concurrently with CLI args.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Ensure root directory is on sys.path
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

from src import config


def parse_args():
    parser = argparse.ArgumentParser(
        description="Launch Delta Liquidity Monitor & Profiler with Resource Monitoring"
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


def main():
    args = parse_args()
    python_exe = sys.executable

    main_script = root_dir / "src" / "main.py"
    monitor_script = root_dir / "monitor" / "ram_monitor.py"

    print("=" * 65)
    print("Launching Delta Liquidity Monitor & Profiler Coordinator")
    print(f"Target: {args.symbol} | Duration: {args.duration}s | Sink: {args.sink.upper()} | Mode: {args.mode.upper()}")
    print("=" * 65)

    collector_cmd = [
        python_exe,
        str(main_script),
        "--symbol", str(args.symbol),
        "--budget", str(args.budget),
        "--duration", str(args.duration),
        "--interval", str(args.interval),
        "--depth", str(args.depth),
        "--sink", str(args.sink),
        "--mode", str(args.mode),
    ]

    # 1. Start Main Collector
    collector_proc = subprocess.Popen(collector_cmd)
    print(f"[Launcher] Collector started (PID: {collector_proc.pid})")

    # 2. Start Resource Monitor with collector's PID
    monitor_proc = subprocess.Popen([python_exe, str(monitor_script), str(collector_proc.pid)])
    print(f"[Launcher] Resource monitor started (PID: {monitor_proc.pid})")

    try:
        # Wait for collector to complete
        collector_proc.wait()
    except KeyboardInterrupt:
        print("\n[Launcher] Shutting down...")
        collector_proc.terminate()
    finally:
        # Stop monitor process
        if monitor_proc.poll() is None:
            time.sleep(1)
            monitor_proc.terminate()

    print("[Launcher] All tasks finished successfully.")


if __name__ == "__main__":
    main()
