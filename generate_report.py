"""
generate_report.py
Generates summary telemetry and microstructure report from SQLite WAL or CSV.
Supports:
- Multi-Instrument Volatility & Liquidity comparison table (Futures vs 0-DTE vs 1-DTE vs 2-DTE)
- Single-symbol Level-2 order book microstructure analysis
- System RAM Working Set verification (< 30 MB)
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
        t_curr = parse_iso(all_data[i].get("timestamp_utc"))
        t_prev = parse_iso(all_data[i - 1].get("timestamp_utc"))
        if t_curr and t_prev:
            diff = (t_curr - t_prev).total_seconds()
            if diff > gap_threshold_seconds:
                session_start_idx = i
                break
    return all_data[session_start_idx:]


def load_expiry_vol_from_sqlite(db_path: Path):
    """Load latest multi-instrument volatility & liquidity records from SQLite."""
    if not db_path.exists():
        return None

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT underlying, expiry_bucket, expiry_date, timestamp_us, timestamp_utc,
                   spot_price, atm_strike, atm_iv_mean, straddle_premium_usd, expected_move_pct,
                   total_ce_bid_lots, total_ce_ask_lots, total_pe_bid_lots, total_pe_ask_lots,
                   lot_imbalance, futures_rv_pct, futures_top_lots
            FROM expiry_liquidity_vol
            ORDER BY timestamp_us ASC;
            """
        )
        cols = [col[0] for col in cursor.description]
        raw_rows = [dict(zip(cols, row)) for row in cursor.fetchall()]

        if not raw_rows:
            return None

        return get_latest_session_data(raw_rows)
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


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


def print_chain_scan_report(chain_records: list, resource_file: Path):
    """Render comparison report for Multi-Instrument Liquidity & Volatility Scanner."""
    resource_data = load_csv(resource_file)
    latest_resource = get_latest_session_data(resource_data)
    ram_usages = [float(row["memory_mb"]) for row in latest_resource if float(row.get("memory_mb", 0)) > 0]
    peak_ram = max([float(row["peak_memory_mb"]) for row in latest_resource]) if latest_resource else 0.0

    t_start = parse_iso(chain_records[0]["timestamp_utc"])
    t_end = parse_iso(chain_records[-1]["timestamp_utc"])
    duration_sec = int((t_end - t_start).total_seconds()) if (t_start and t_end) else 0

    print("=" * 105)
    print("      DELTA EXCHANGE MULTI-INSTRUMENT LIQUIDITY & VOLATILITY SCANNER REPORT")
    print(f"      Session Records: {len(chain_records)} | Duration: {duration_sec}s | Storage: SQLite WAL (Lossless Decimal TEXT)")
    print("=" * 105)

    # Group latest rows by underlying
    underlyings = sorted(list(set(r["underlying"] for r in chain_records)))

    for asset in underlyings:
        asset_rows = [r for r in chain_records if r["underlying"] == asset]
        latest_ts = max(r["timestamp_us"] for r in asset_rows)
        latest_snapshot = [r for r in asset_rows if r["timestamp_us"] == latest_ts]

        spot = float(latest_snapshot[0]["spot_price"])
        rv_ann = float(latest_snapshot[0]["futures_rv_pct"])
        fut_lots = int(latest_snapshot[0]["futures_top_lots"])

        print(f"\n>> UNDERLYING: {asset} | Current Spot: ${spot:,.2f} | Futures Top Lots: {fut_lots:,} | Futures RV: {rv_ann:.2f}%")
        print("-" * 105)
        print(f"{'Instrument / Expiry':<20} | {'Expiry Date':<11} | {'ATM Strike':<12} | {'Bid Lots':<10} | {'Ask Lots':<10} | {'Imbalance':<10} | {'ATM IV %':<10} | {'Expected Move'}")
        print("-" * 105)

        for bucket in ("0-DTE", "1-DTE", "2-DTE"):
            bucket_row = [r for r in latest_snapshot if r["expiry_bucket"] == bucket]
            if not bucket_row:
                continue
            r = bucket_row[0]
            exp_date = r["expiry_date"]
            atm_strike = float(r["atm_strike"])
            total_bids = int(r["total_ce_bid_lots"]) + int(r["total_pe_bid_lots"])
            total_asks = int(r["total_ce_ask_lots"]) + int(r["total_pe_ask_lots"])
            imb = float(r["lot_imbalance"])
            iv_pct = float(r["atm_iv_mean"]) * 100.0
            straddle = float(r["straddle_premium_usd"])
            move_pct = float(r["expected_move_pct"])

            print(f"{bucket:<20} | {exp_date:<11} | ${atm_strike:<11,.1f} | {total_bids:<10,d} | {total_asks:<10,d} | {imb:+9.4f} | {iv_pct:8.2f}% | ${straddle:,.2f} ({move_pct:.2f}%)")

        print("-" * 105)

    print("\nSYSTEM RESOURCE PROFILER:")
    if ram_usages:
        print(f"   • Average RAM Usage   : {sum(ram_usages)/len(ram_usages):.2f} MB")
    print(f"   • Peak Working Set RAM: {peak_ram:.2f} MB (Ceiling: < 30.00 MB)")
    if peak_ram > 0:
        compliance = "PASSED (< 30 MB)" if peak_ram < 30.0 else "EXCEEDED"
        print(f"   • Memory Discipline   : {compliance}")
    print("=" * 105)


def generate_summary(source="auto"):
    root = Path(__file__).resolve().parent
    db_file = root / "data" / "telemetry.db"
    metrics_file = root / "data" / "analysis" / "metrics.csv"
    resource_file = root / "logs" / "system_resources.csv"

    # 1. First check if multi-instrument chain scan data exists in SQLite
    if source in ("auto", "sqlite"):
        chain_records = load_expiry_vol_from_sqlite(db_file)
        if chain_records:
            print_chain_scan_report(chain_records, resource_file)
            return

    # 2. Otherwise load single-symbol L2 orderbook telemetry
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
    latest_resource = get_latest_session_data(resource_data)
    ram_usages = [float(row["memory_mb"]) for row in latest_resource if float(row.get("memory_mb", 0)) > 0]
    peak_ram = max([float(row["peak_memory_mb"]) for row in latest_resource]) if latest_resource else 0.0

    t_start = parse_iso(records[0]["timestamp_utc"])
    t_end = parse_iso(records[-1]["timestamp_utc"])
    duration_str = f"{int((t_end - t_start).total_seconds())}s" if (t_start and t_end) else "N/A"

    mid_prices = [float(row["mid_price"]) for row in records]
    spreads = [float(row["spread"]) for row in records]
    spread_pcts = [float(row["spread_percent"]) for row in records]
    bid_volumes = [float(row["bid_notional_usd"]) for row in records]
    ask_volumes = [float(row["ask_notional_usd"]) for row in records]
    imbalances = [float(row["imbalance"]) for row in records]

    latencies = [
        float(row["rtt_latency_ns"]) / 1_000_000.0
        for row in records
        if row.get("rtt_latency_ns") and int(row["rtt_latency_ns"]) > 0
    ]

    buy_slippages = []
    sell_slippages = []
    for row in records:
        if "simulations" in row:
            sims = row["simulations"]
            if "buy_taker" in sims:
                buy_slippages.append(float(sims["buy_taker"]["slippage_percent"]))
            if "sell_taker" in sims:
                sell_slippages.append(float(sims["sell_taker"]["slippage_percent"]))

    print("=" * 68)
    print(f"      DELTA EXCHANGE LIQUIDITY & TELEMETRY REPORT")
    print(f"      Data Source: {data_source_label}")
    print("=" * 68)
    print(f"Snapshots in Session     : {len(records)} | Duration: {duration_str}")
    print("-" * 68)
    print("1. PRICE & SPREAD DYNAMICS:")
    print(f"   • Starting Mid Price  : ${mid_prices[0]:,.2f}")
    print(f"   • Ending Mid Price    : ${mid_prices[-1]:,.2f}")
    print(f"   • Price Movement      : ${mid_prices[-1] - mid_prices[0]:+,.2f}")
    print(f"   • Average Spread      : ${sum(spreads)/len(spreads):.4f} ({sum(spread_pcts)/len(spread_pcts):.6f}%)")
    print("-" * 68)
    print("2. ORDER BOOK DEPTH & FLOW PRESSURE:")
    print(f"   • Avg Bid Depth (USD) : ${sum(bid_volumes)/len(bid_volumes):,.2f}")
    print(f"   • Avg Ask Depth (USD) : ${sum(ask_volumes)/len(ask_volumes):,.2f}")
    avg_imb = sum(imbalances) / len(imbalances)
    print(f"   • Avg Imbalance Index : {avg_imb:+.4f}")
    print("-" * 68)
    print("3. EXECUTION MODELING:")
    if buy_slippages:
        print(f"   • Avg Taker Buy Slip  : {sum(buy_slippages)/len(buy_slippages):.6f}%")
    if sell_slippages:
        print(f"   • Avg Taker Sell Slip : {sum(sell_slippages)/len(sell_slippages):.6f}%")
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
