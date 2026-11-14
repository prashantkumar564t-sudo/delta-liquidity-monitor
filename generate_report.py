"""
generate_report.py
Generates summary telemetry and microstructure report from SQLite WAL or CSV.
Supports CLI arguments (--source auto|sqlite|csv).
"""

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def load_csv(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_iso(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def get_latest_session_data(all_data, gap_threshold_seconds=10):
    """Detects where the latest run started by checking time gaps between snapshots."""
    if not all_data:
        return []

    session_start_idx = 0
    for i in range(len(all_data) - 1, 0, -1):
        t_curr = parse_iso(all_data[i]["timestamp_utc"])
        t_prev = parse_iso(all_data[i - 1]["timestamp_utc"])
        if t_curr and t_prev:
            diff = (t_curr - t_prev).total_seconds()
            if diff > gap_threshold_seconds:
                session_start_idx = i
                break
    return all_data[session_start_idx:]


def load_from_sqlite(db_path: Path):
    """Load latest session metrics and simulations from SQLite WAL."""
    if not db_path.exists():
        return None

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT symbol, timestamp_us, timestamp_utc, exchange_timestamp,
                   best_bid, best_ask, mid_price, spread, spread_percent,
                   bid_contracts, ask_contracts, bid_btc, ask_btc,
                   bid_notional_usd, ask_notional_usd, imbalance, rtt_latency_ns
            FROM l2_snapshots
            ORDER BY timestamp_us ASC;
            """
        )
        cols = [col[0] for col in cursor.description]
        raw_rows = [dict(zip(cols, row)) for row in cursor.fetchall()]

        if not raw_rows:
            return None

        latest_snapshots = get_latest_session_data(raw_rows)
        start_us = latest_snapshots[0]["timestamp_us"]
        end_us = latest_snapshots[-1]["timestamp_us"]

        # Fetch matching simulations
        cursor.execute(
            """
            SELECT timestamp_us, side, order_type, requested_usd,
                   executed_notional_usd, slippage_usd, slippage_percent,
                   fee_usd, queue_depth_ahead
            FROM execution_simulations
            WHERE timestamp_us >= ? AND timestamp_us <= ?;
            """,
            (start_us, end_us)
        )
        sim_cols = [col[0] for col in cursor.description]
        sim_rows = [dict(zip(sim_cols, row)) for row in cursor.fetchall()]

        # Map simulations by timestamp_us
        sims_by_ts = {}
        for sim in sim_rows:
            ts = sim["timestamp_us"]
            key = f"{sim['side']}_{sim['order_type']}"
            if ts not in sims_by_ts:
                sims_by_ts[ts] = {}
            sims_by_ts[ts][key] = sim

        for snap in latest_snapshots:
            snap["simulations"] = sims_by_ts.get(snap["timestamp_us"], {})

        return latest_snapshots

    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def generate_summary(source="auto"):
    root = Path(__file__).resolve().parent
    db_file = root / "data" / "telemetry.db"
    metrics_file = root / "data" / "analysis" / "metrics.csv"
    resource_file = root / "logs" / "system_resources.csv"

    records = None
    data_source_label = "CSV"

    if source in ("auto", "sqlite"):
        records = load_from_sqlite(db_file)
        if records:
            data_source_label = "SQLite WAL (Lossless Decimal TEXT)"

    if not records and source in ("auto", "csv"):
        all_metrics = load_csv(metrics_file)
        if all_metrics:
            records = get_latest_session_data(all_metrics)
            data_source_label = "CSV"

    if not records:
        print("[!] No metrics data found. Run launcher.py first.")
        return

    resource_data = load_csv(resource_file)

    t_start = parse_iso(records[0]["timestamp_utc"])
    t_end = parse_iso(records[-1]["timestamp_utc"])
    if t_start and t_end:
        duration_sec = int((t_end - t_start).total_seconds())
        duration_str = f"{duration_sec // 60}m {duration_sec % 60}s ({duration_sec}s)"
    else:
        duration_str = "N/A"

    # Price & Spread dynamics
    mid_prices = [float(row["mid_price"]) for row in records]
    spreads = [float(row["spread"]) for row in records]
    spread_pcts = [float(row["spread_percent"]) for row in records]

    # Liquidity
    bid_volumes = [float(row["bid_notional_usd"]) for row in records]
    ask_volumes = [float(row["ask_notional_usd"]) for row in records]
    imbalances = [float(row["imbalance"]) for row in records]

    # Latencies
    latencies = [
        float(row["rtt_latency_ns"]) / 1_000_000.0
        for row in records
        if row.get("rtt_latency_ns") and int(row["rtt_latency_ns"]) > 0
    ]

    # Slippage & Maker queues
    buy_slippages = []
    sell_slippages = []
    maker_queues = []

    for row in records:
        if "simulations" in row:
            sims = row["simulations"]
            if "buy_taker" in sims:
                buy_slippages.append(float(sims["buy_taker"]["slippage_percent"]))
            if "sell_taker" in sims:
                sell_slippages.append(float(sims["sell_taker"]["slippage_percent"]))
            if "buy_maker" in sims and sims["buy_maker"].get("queue_depth_ahead") is not None:
                maker_queues.append(int(sims["buy_maker"]["queue_depth_ahead"]))
        else:
            try:
                buy_info = json.loads(row.get("buy_slippage_json", "{}"))
                sell_info = json.loads(row.get("sell_slippage_json", "{}"))
                if "slippage_percent" in buy_info:
                    buy_slippages.append(float(buy_info["slippage_percent"]))
                if "slippage_percent" in sell_info:
                    sell_slippages.append(float(sell_info["slippage_percent"]))
            except Exception:
                pass

    # Filter resource metrics for the current session
    latest_resource = get_latest_session_data(resource_data)
    ram_usages = [float(row["memory_mb"]) for row in latest_resource if float(row.get("memory_mb", 0)) > 0]
    peak_ram = max([float(row["peak_memory_mb"]) for row in latest_resource]) if latest_resource else 0.0

    print("=" * 68)
    print(f"      DELTA EXCHANGE LIQUIDITY & TELEMETRY REPORT")
    print(f"      Data Source: {data_source_label}")
    print("=" * 68)
    print(f"Snapshots in Session     : {len(records)}")
    print(f"Exact Duration           : {duration_str}")
    print(f"Session Start Time (UTC) : {records[0]['timestamp_utc']}")
    print(f"Session End Time (UTC)   : {records[-1]['timestamp_utc']}")
    print("-" * 68)
    print("1. PRICE & SPREAD DYNAMICS:")
    print(f"   • Starting Mid Price  : ${mid_prices[0]:,.2f}")
    print(f"   • Ending Mid Price    : ${mid_prices[-1]:,.2f}")
    print(f"   • Price Movement      : ${mid_prices[-1] - mid_prices[0]:+,.2f}")
    print(f"   • Min / Max Mid Price : ${min(mid_prices):,.2f} / ${max(mid_prices):,.2f}")
    print(f"   • Average Spread      : ${sum(spreads)/len(spreads):.4f} ({sum(spread_pcts)/len(spread_pcts):.6f}%)")
    print("-" * 68)
    print("2. ORDER BOOK DEPTH & FLOW PRESSURE:")
    print(f"   • Avg Bid Depth (USD) : ${sum(bid_volumes)/len(bid_volumes):,.2f}")
    print(f"   • Avg Ask Depth (USD) : ${sum(ask_volumes)/len(ask_volumes):,.2f}")
    avg_imbalance = sum(imbalances) / len(imbalances)
    dominance = "Bids Dominant (Buy Pressure)" if avg_imbalance > 0 else "Asks Dominant (Sell Pressure)"
    print(f"   • Avg Imbalance Index : {avg_imbalance:+.4f} ({dominance})")
    print("-" * 68)
    print("3. EXECUTION MODELING:")
    if buy_slippages:
        print(f"   • Avg Taker Buy Slip  : {sum(buy_slippages)/len(buy_slippages):.6f}%")
    if sell_slippages:
        print(f"   • Avg Taker Sell Slip : {sum(sell_slippages)/len(sell_slippages):.6f}%")
    if maker_queues:
        print(f"   • Avg Maker Queue     : {sum(maker_queues)/len(maker_queues):.1f} contracts ahead at best bid")
    if latencies:
        print(f"   • Avg REST Latency    : {sum(latencies)/len(latencies):.2f} ms")
    print("-" * 68)
    print("4. SYSTEM RESOURCE PROFILER:")
    if ram_usages:
        print(f"   • Average RAM Usage   : {sum(ram_usages)/len(ram_usages):.2f} MB")
    print(f"   • Peak Working Set RAM: {peak_ram:.2f} MB (Ceiling: < 30.00 MB)")
    if peak_ram > 0:
        compliance = "PASSED (< 30 MB)" if peak_ram < 30.0 else "EXCEEDED"
        print(f"   • Memory Discipline   : {compliance}")
    print("=" * 68)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate Liquidity Telemetry Summary Report"
    )
    parser.add_argument(
        "--source",
        choices=["auto", "sqlite", "csv"],
        default="auto",
        help="Data storage source to generate report from (default: auto)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate_summary(source=args.source)
