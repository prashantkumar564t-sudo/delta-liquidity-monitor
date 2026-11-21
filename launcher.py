"""
launcher.py
Launches the Multi-Instrument Scanner / Collector and the RAM/Resource monitor concurrently with CLI args.
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
        description="Launch Delta Multi-Instrument Scanner & Profiler Coordinator"
    )
    parser.add_argument(
        "--mode",
        choices=["options-otm", "chain-scan", "multi-perp", "ws", "rest"],
        default="options-otm",
        help="Scanner mode: options-otm (OTM Options Scanner), multi-perp (All 5 Perpetuals), chain-scan (Perps + 0/1/2-DTE Options) or ws/rest (Single Symbol)",
    )
    parser.add_argument(
        "--symbols",
        default="BTCUSD,ETHUSD,SOLUSD,PAXGUSD,SLVONUSD",
        help="Comma-separated symbols for multi-perp (default: BTCUSD,ETHUSD,SOLUSD,PAXGUSD,SLVONUSD)",
    )
    parser.add_argument(
        "--underlyings",
        default="BTC,ETH,PAXG,XAUT",
        help="Comma-separated assets for chain-scan / options-otm (default: BTC,ETH,PAXG,XAUT)",
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
        "--duration-minutes",
        type=int,
        default=None,
        help="Timed cloud run duration in minutes (e.g. 1 for testing, 300 for 5-hour evening run). Bypasses IST idle sleep.",
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


def main():
    args = parse_args()
    python_exe = sys.executable

    main_script = root_dir / "src" / "main.py"
    monitor_script = root_dir / "monitor" / "ram_monitor.py"

    run_duration = args.duration
    if args.duration_minutes is not None:
        run_duration = args.duration_minutes * 60
        print(f"[Launcher] Timed Cloud Mode: {args.duration_minutes}m run ({run_duration}s) | Bypassing IST idle window")

    print("=" * 70)
    print("Launching Delta Multi-Instrument Scanner Coordinator")
    print(f"Mode: {args.mode.upper()} | Underlyings: {args.underlyings} | Duration: {run_duration}s | Sink: {args.sink.upper()}")
    print("=" * 70)

    collector_cmd = [
        python_exe,
        str(main_script),
        "--mode", str(args.mode),
        "--underlyings", str(args.underlyings),
        "--symbols", str(args.symbols),
        "--symbol", str(args.symbol),
        "--budget", str(args.budget),
        "--duration", str(run_duration),
        "--interval", str(args.interval),
        "--depth", str(args.depth),
        "--sink", str(args.sink),
    ]
    if args.duration_minutes is not None:
        collector_cmd.extend(["--duration-minutes", str(args.duration_minutes)])

    # 1. Start Main Collector
    collector_proc = subprocess.Popen(collector_cmd)
    print(f"[Launcher] Scanner/Collector started (PID: {collector_proc.pid})")

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
