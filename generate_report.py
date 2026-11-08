"""
generate_report.py
Generates summary report specifically for the LATEST collection session.
"""

import csv
import json
from datetime import datetime
from pathlib import Path


def load_csv(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_iso(ts_str):
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def get_latest_session_data(all_data, gap_threshold_seconds=10):
    """Detects where the latest run started by checking time gaps between snapshots."""
    if not all_data:
        return []

    # Iterate backwards to find when the last run started
    session_start_idx = 0
    for i in range(len(all_data) - 1, 0, -1):
        t_curr = parse_iso(all_data[i]["timestamp_utc"])
        t_prev = parse_iso(all_data[i - 1]["timestamp_utc"])
        
        if t_curr and t_prev:
            diff = (t_curr - t_prev).total_seconds()
            if diff > gap_threshold_seconds:
                # Big gap found! The latest session starts at index i
                session_start_idx = i
                break

    return all_data[session_start_idx:]


def generate_summary():
    root = Path(__file__).resolve().parent
    metrics_file = root / "data" / "analysis" / "metrics.csv"
    resource_file = root / "logs" / "system_resources.csv"

    all_metrics = load_csv(metrics_file)
    resource_data = load_csv(resource_file)

    if not all_metrics:
        print("[!] No metrics data found. Run launcher.py first.")
        return

    # सिर्फ सबसे ताज़ा (Current) रन का डेटा लें
    latest_metrics = get_latest_session_data(all_metrics)

    t_start = parse_iso(latest_metrics[0]["timestamp_utc"])
    t_end = parse_iso(latest_metrics[-1]["timestamp_utc"])
    
    if t_start and t_end:
        duration_sec = int((t_end - t_start).total_seconds())
        duration_str = f"{duration_sec // 60}m {duration_sec % 60}s"
    else:
        duration_str = "5m 00s"

    # Price & Spread (सिर्फ ताज़ा रन के)
    mid_prices = [float(row["mid_price"]) for row in latest_metrics]
    spreads = [float(row["spread"]) for row in latest_metrics]
    spread_pcts = [float(row["spread_percent"]) for row in latest_metrics]

    # Liquidity
    bid_volumes_usd = [float(row["bid_notional_usd"]) for row in latest_metrics]
    ask_volumes_usd = [float(row["ask_notional_usd"]) for row in latest_metrics]
    imbalances = [float(row["imbalance"]) for row in latest_metrics]

    # Slippage
    buy_slippages = []
    sell_slippages = []
    for row in latest_metrics:
        try:
            buy_info = json.loads(row.get("buy_slippage_json", "{}"))
            sell_info = json.loads(row.get("sell_slippage_json", "{}"))
            buy_slippages.append(float(buy_info.get("slippage_percent", 0.0)))
            sell_slippages.append(float(sell_info.get("slippage_percent", 0.0)))
        except Exception:
            pass

    # RAM
    ram_usages = [float(row["memory_mb"]) for row in resource_data if float(row["memory_mb"]) > 0]
    peak_ram = max([float(row["peak_memory_mb"]) for row in resource_data]) if resource_data else 0.0

    print("=" * 65)
    print("      DELTA EXCHANGE BTC-USD REPORT (LATEST 5-MIN RUN)      ")
    print("=" * 65)
    print(f"Snapshots in This Run    : {len(latest_metrics)} (Total History: {len(all_metrics)})")
    print(f"Exact Run Duration       : {duration_str}")
    print(f"Session Start Time (UTC) : {latest_metrics[0]['timestamp_utc']}")
    print(f"Session End Time (UTC)   : {latest_metrics[-1]['timestamp_utc']}")
    print("-" * 65)
    print("1. PRICE & SPREAD DYNAMICS (THIS RUN):")
    print(f"   • Starting Mid Price  : ${mid_prices[0]:,.2f}")
    print(f"   • Ending Mid Price    : ${mid_prices[-1]:,.2f}")
    print(f"   • Price Movement      : ${mid_prices[-1] - mid_prices[0]:+,.2f}")
    print(f"   • Min / Max Mid Price : ${min(mid_prices):,.2f} / ${max(mid_prices):,.2f}")
    print(f"   • Average Spread      : ${sum(spreads)/len(spreads):.4f} ({sum(spread_pcts)/len(spread_pcts):.6f}%)")
    print("-" * 65)
    print("2. ORDER BOOK DEPTH & PRESSURE:")
    print(f"   • Avg Bid Depth (USD) : ${sum(bid_volumes_usd)/len(bid_volumes_usd):,.2f}")
    print(f"   • Avg Ask Depth (USD) : ${sum(ask_volumes_usd)/len(ask_volumes_usd):,.2f}")
    avg_imbalance = sum(imbalances)/len(imbalances)
    side_dominance = "Bids Dominant (Buy Pressure)" if avg_imbalance > 0 else "Asks Dominant (Sell Pressure)"
    print(f"   • Avg Order Imbalance : {avg_imbalance:+.4f} ({side_dominance})")
    print("-" * 65)
    print("3. EXECUTION SLIPPAGE ($1,000 Order):")
    if buy_slippages:
        print(f"   • Avg Buy Slippage    : {sum(buy_slippages)/len(buy_slippages):.6f}%")
    if sell_slippages:
        print(f"   • Avg Sell Slippage   : {sum(sell_slippages)/len(sell_slippages):.6f}%")
    print("-" * 65)
    print("4. SYSTEM RESOURCE PROFILER:")
    if ram_usages:
        print(f"   • Average RAM Usage   : {sum(ram_usages)/len(ram_usages):.2f} MB")
    print(f"   • Peak RAM Usage      : {peak_ram:.2f} MB")
    print("=" * 65)


if __name__ == "__main__":
    generate_summary()