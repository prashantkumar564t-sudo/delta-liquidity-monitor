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
import os
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Ensure root directory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.delta_api import DeltaAPI
from src.delta_ws import DeltaWebSocketClient
from src.instruments import InstrumentDiscovery, discover_otm_options
from src.orderbook import OrderBookAnalyzer
from src.slippage import SlippageCalculator
from src.storage import CSVStorage, SQLiteStorage, export_session_to_parquet
from src.volatility import OptionsVolatilityEngine, RollingRealizedVolatility

DEFAULT_PERP_CONFIGS = {
    "BTCUSD": {"contract_value": Decimal("0.001"), "label": "Bitcoin"},
    "ETHUSD": {"contract_value": Decimal("0.01"), "label": "Ethereum"},
    "SOLUSD": {"contract_value": Decimal("1.0"), "label": "Solana"},
    "PAXGUSD": {"contract_value": Decimal("0.001"), "label": "Gold"},
    "XAUTUSD": {"contract_value": Decimal("0.001"), "label": "Tether Gold"},
    "SLVONUSD": {"contract_value": Decimal("0.1"), "label": "Silver"},
}


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
    print("Tracking: Perpetuals + 0-DTE, 1-DTE, 2-DTE Options (ATM ± 5 Strikes)")
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
            timestamp_utc = datetime.now(UTC).isoformat()
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
                    mid_price = (best_bid + best_ask) / Decimal(2)
                    spread = best_ask - best_bid
                    fut_bid_lots = int(q.get("bid_size") or 0)
                    fut_ask_lots = int(q.get("ask_size") or 0)
                    fut_top_lots = fut_bid_lots + fut_ask_lots

                    # Update Rolling Realized Volatility
                    rv_info = rv_engines[asset].update(mid_price, spread)
                    rv_annualized = rv_info["rv_annualized_pct"]

                    expiries = asset_info.get("expiries", {})
                    expiries.get("0-DTE", {})
                    expiries.get("1-DTE", {})

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
                            dte0_iv = f"{vol_metrics['mean_atm_iv'] * Decimal(100):.1f}%"
                            dte0_move = f"{vol_metrics['expected_move_pct']:.2f}%"
                        elif b_name == "1-DTE":
                            dte1_iv = f"{vol_metrics['mean_atm_iv'] * Decimal(100):.1f}%"

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
            timestamp_utc = datetime.now(UTC).isoformat()
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


def run_multi_perp_collector(
    symbols_str="BTCUSD,ETHUSD,SOLUSD,PAXGUSD,SLVONUSD",
    duration=config.COLLECTION_DURATION,
    interval=config.SNAPSHOT_INTERVAL,
    depth=config.DEPTH,
    sink="both",
    budgets=(100.0, 500.0, 1000.0, 5000.0, 10000.0),
):
    import concurrent.futures

    symbols = [s.strip().upper() for s in symbols_str.split(",") if s.strip()]
    iteration_count = 0
    total_snapshots = 0
    errors_count = 0

    print("=" * 75)
    print("Starting Delta Multi-Perpetual Liquidity & Microstructure Collector")
    print(f"Symbols: {', '.join(symbols)} | Duration: {duration}s | Interval: {interval}s | Depth: {depth}")
    print(f"Budgets: {[f'${int(b)}' for b in budgets]} | Storage Sink: {sink.upper()}")
    print("=" * 75)

    rest_api = DeltaAPI(timeout=config.API_TIMEOUT)
    csv_storage = CSVStorage() if sink in ("csv", "both") else None
    sqlite_storage = SQLiteStorage() if sink in ("sqlite", "both") else None

    analyzers = {}
    slippage_calcs = {}
    for sym in symbols:
        cval = DEFAULT_PERP_CONFIGS.get(sym, {}).get("contract_value", Decimal("0.001"))
        analyzers[sym] = OrderBookAnalyzer(contract_value=cval)
        slippage_calcs[sym] = SlippageCalculator(
            contract_value=cval,
            taker_fee=config.TAKER_FEE,
            maker_fee=config.MAKER_FEE,
        )

    trim_process_memory()
    start_time = time.monotonic()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(symbols)) as executor:
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= duration:
                    print("\n[+] Configured collection duration completed.")
                    break

                loop_start = time.monotonic()
                timestamp_utc = datetime.now(UTC).isoformat()
                timestamp_us = int(time.time() * 1_000_000)

                futures = {
                    executor.submit(rest_api.get_orderbook, sym, depth): sym
                    for sym in symbols
                }

                summary_snippets = []
                for fut in concurrent.futures.as_completed(futures):
                    sym = futures[fut]
                    try:
                        orderbook = fut.result()
                        if not orderbook:
                            errors_count += 1
                            continue

                        analyzer = analyzers[sym]
                        calc = slippage_calcs[sym]

                        metrics = analyzer.analyze(orderbook)
                        rtt_ns = rest_api.last_rtt_ns

                        # Calculate simulations across requested budgets
                        slippage_results = {}
                        for b in budgets:
                            b_val = float(b)
                            buy_sim = calc.simulate(orderbook, order_usd=b_val, side="buy")
                            sell_sim = calc.simulate(orderbook, order_usd=b_val, side="sell")
                            slippage_results[f"buy_taker_{int(b_val)}"] = buy_sim
                            slippage_results[f"sell_taker_{int(b_val)}"] = sell_sim

                        # Calculate maker queue simulations
                        buy_maker = calc.simulate_maker(
                            orderbook, limit_price=metrics["best_bid"], size_contracts=10, side="buy"
                        )
                        sell_maker = calc.simulate_maker(
                            orderbook, limit_price=metrics["best_ask"], size_contracts=10, side="sell"
                        )
                        slippage_results["buy_maker"] = buy_maker
                        slippage_results["sell_maker"] = sell_maker

                        if csv_storage:
                            csv_storage.write_raw_orderbook(
                                orderbook=orderbook, symbol=sym, timestamp=timestamp_utc
                            )

                        if sqlite_storage:
                            sqlite_storage.write_snapshot_and_metrics(
                                symbol=sym,
                                orderbook=orderbook,
                                metrics=metrics,
                                slippage_results=slippage_results,
                                timestamp_utc=timestamp_utc,
                                timestamp_us=timestamp_us,
                                rtt_latency_ns=rtt_ns,
                            )

                        total_snapshots += 1
                        summary_snippets.append(
                            f"{sym}: ${metrics['mid_price']:,.2f} (Spr: {metrics['spread_percent']:.4f}%)"
                        )

                    except Exception:
                        errors_count += 1

                iteration_count += 1
                lead = f"\r[{iteration_count:04d} | {int(elapsed):3d}s/{duration}s] "
                sys.stdout.write(lead + " | ".join(summary_snippets[:3]))
                sys.stdout.flush()

                iteration_time = time.monotonic() - loop_start
                sleep_time = max(0.0, interval - iteration_time)
                trim_process_memory()
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[!] Multi-perpetual collection stopped by user.")
    finally:
        if sqlite_storage:
            sqlite_storage.close()

    print("\n" + "=" * 75)
    print("Multi-Perpetual Collection Complete!")
    print(f"Total Iterations: {iteration_count} | Total Snapshots: {total_snapshots} | Errors: {errors_count}")
    print("=" * 75)


def print_otm_summary_table(since_timestamp_us=None, db_path=None):
    """Query telemetry.db and print aggregated OTM options liquidity summary."""
    import sqlite3
    from pathlib import Path
    if db_path is None:
        db_path = Path(__file__).resolve().parent.parent / "data" / "telemetry.db"

    if not Path(db_path).exists():
        print("[!] No telemetry database found.")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    where_clause = "WHERE timestamp_us >= ?" if since_timestamp_us else ""
    params = (since_timestamp_us,) if since_timestamp_us else ()

    query = f"""
    SELECT 
        underlying,
        expiry_bucket,
        CASE 
            WHEN abs(delta) < 0.11 THEN '0.08-0.11'
            WHEN abs(delta) < 0.14 THEN '0.11-0.14'
            WHEN abs(delta) < 0.18 THEN '0.14-0.18'
            ELSE '0.18-0.25'
        END AS delta_band,
        count(*) as samples,
        avg(mark_price) as avg_mark,
        avg(best_bid) as avg_bid,
        avg(best_ask) as avg_ask,
        avg(bid_size) as avg_bid_size,
        avg(bid_slippage_pct) as avg_bid_slip_pct,
        avg(spread_vs_mark_pct) as avg_spread_vs_mark_pct
    FROM otm_options_liquidity
    {where_clause}
    GROUP BY underlying, expiry_bucket, delta_band
    ORDER BY underlying, expiry_bucket, delta_band;
    """

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        if not rows:
            print("[*] No OTM options records found in the specified window.")
            return

        print("\n" + "=" * 115)
        print("OPTIONS OTM LIQUIDITY BASELINE SUMMARY (Grouped by Underlying, Expiry & Delta Band)")
        print("=" * 115)
        header = f"{'Underlying':<10} | {'Expiry':<7} | {'Delta Band':<10} | {'Samples':<7} | {'Avg Mark':<12} | {'Avg Bid':<12} | {'Avg Ask':<12} | {'Avg Bid Size':<12} | {'Bid Slip %':<10} | {'Spr/Mark %':<10}"
        print(header)
        print("-" * 115)
        for r in rows:
            u, exp, band, cnt, mark_p, b_bid, b_ask, b_size, slip_pct, spr_pct = r
            print(
                f"{u:<10} | {exp:<7} | {band:<10} | {cnt:<7} | "
                f"${mark_p:>10.2f} | ${b_bid:>10.2f} | ${b_ask:>10.2f} | "
                f"{b_size:>12.1f} | {slip_pct:>9.2f}% | {spr_pct:>9.2f}%"
            )
        print("=" * 115 + "\n")
    except Exception as e:
        print(f"[!] Error querying summary table: {e}")
    finally:
        conn.close()


def run_options_otm_scanner(
    underlyings_str="BTC,ETH,PAXG,XAUT",
    duration=300,
    interval=5.0,
    min_delta=0.07,
    max_delta=0.25,
    sink="sqlite",
    capture_l2=True,
    export_parquet=True,
):
    import concurrent.futures

    underlyings = tuple(u.strip().upper() for u in underlyings_str.split(",") if u.strip())
    scan_count = 0
    total_records = 0
    total_l2_records = 0
    errors_count = 0

    print("=" * 75)
    print("Starting Delta Options OTM Liquidity Scanner (--mode options-otm)")
    print(f"Underlyings: {', '.join(underlyings)} | Delta Band: [{min_delta:.2f}, {max_delta:.2f}]")
    print(f"Duration: {duration}s ({duration // 60}m) | Polling Interval: {interval}s | Expiries: 0-DTE, 1-DTE")
    print(f"Storage Sink: {sink.upper()} (data/telemetry.db -> otm_options_liquidity & l2_snapshots)")
    print("=" * 75)

    discovery = InstrumentDiscovery(timeout=config.API_TIMEOUT)
    rest_api = DeltaAPI(timeout=config.API_TIMEOUT) if capture_l2 else None
    sqlite_storage = SQLiteStorage() if sink in ("sqlite", "both") else None

    # Perpetual symbols for underlying L2 orderbook capture
    perp_symbols = [f"{u}USD" for u in underlyings]
    analyzers = {
        sym: OrderBookAnalyzer(
            contract_value=DEFAULT_PERP_CONFIGS.get(sym, {}).get("contract_value", Decimal("0.001"))
        )
        for sym in perp_symbols
    }

    session_start_us = int(time.time() * 1_000_000)
    session_dt_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    trim_process_memory()
    start_time = time.monotonic()

    try:
        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= duration:
                print("\n[+] Configured scan duration completed.")
                break

            loop_start = time.monotonic()
            timestamp_us = int(time.time() * 1_000_000)
            timestamp_utc = datetime.now(UTC).isoformat()
            ist_dt = datetime.now(timezone(timedelta(hours=5, minutes=30)))
            datetime_ist = ist_dt.strftime("%Y-%m-%d %H:%M:%S")

            try:
                # 1. Capture 0-DTE & 1-DTE OTM Options across BTC, ETH, PAXG, XAUT
                otm_opts = discover_otm_options(
                    client=discovery,
                    underlyings=underlyings,
                    min_delta=min_delta,
                    max_delta=max_delta,
                )

                if otm_opts and sqlite_storage:
                    sqlite_storage.write_otm_options_liquidity(
                        otm_opts, timestamp_us=timestamp_us, datetime_ist=datetime_ist
                    )

                scan_count += 1
                total_records += len(otm_opts)

                # 2. Capture L2 Orderbook for Underlyings (BTCUSD, ETHUSD, PAXGUSD, XAUTUSD)
                l2_count_this_loop = 0
                if capture_l2 and rest_api and sqlite_storage:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=len(perp_symbols)) as executor:
                        future_to_sym = {
                            executor.submit(rest_api.get_orderbook, sym, config.DEPTH): sym
                            for sym in perp_symbols
                        }
                        for fut in concurrent.futures.as_completed(future_to_sym):
                            sym = future_to_sym[fut]
                            try:
                                book = fut.result()
                                if book and book.get("buy") and book.get("sell"):
                                    metrics = analyzers[sym].analyze(book)
                                    sqlite_storage.write_snapshot_and_metrics(
                                        symbol=sym,
                                        orderbook=book,
                                        metrics=metrics,
                                        timestamp_utc=timestamp_utc,
                                        timestamp_us=timestamp_us,
                                        rtt_latency_ns=rest_api.last_rtt_ns,
                                    )
                                    l2_count_this_loop += 1
                            except Exception:
                                pass
                    total_l2_records += l2_count_this_loop

                if sqlite_storage:
                    sqlite_storage.flush()

                avg_bid_slip = (
                    sum(o["bid_slippage_pct"] for o in otm_opts) / len(otm_opts)
                    if otm_opts else 0.0
                )
                avg_spread_mark = (
                    sum(o["spread_vs_mark_pct"] for o in otm_opts) / len(otm_opts)
                    if otm_opts else 0.0
                )

                lead = f"\r[{scan_count:04d} | {int(elapsed):3d}s/{duration}s] "
                status_display = (
                    f"{lead}Discovered: {len(otm_opts)} OTM opts | L2: {l2_count_this_loop} books | "
                    f"Avg Bid Slip: {avg_bid_slip:.2f}% | "
                    f"Avg Spread vs Mark: {avg_spread_mark:.2f}%"
                )
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

    print("\n" + "=" * 75)
    print("Options OTM & L2 Orderbook Scan Complete!")
    print(f"Total Scans: {scan_count} | Total Options Records: {total_records} | L2 Books: {total_l2_records} | Errors: {errors_count}")
    print("=" * 75)

    print_otm_summary_table(session_start_us)

    export_meta = None
    if export_parquet:
        try:
            print("\n[+] Exporting session rows to ZSTD Parquet via DuckDB...")
            export_meta = export_session_to_parquet(
                session_start_us=session_start_us,
                session_dt_ist=session_dt_ist,
                table_name="otm_options_liquidity",
            )
            print(f"[+] Parquet Export Success: {export_meta['export_path']}")
            print(f"    Rows: {export_meta['row_count']:,} | Size: {export_meta['file_size_kb']} KB (ZSTD)")
        except Exception as e:
            print(f"[!] Parquet export error: {e}")

    return export_meta


def parse_args():
    parser = argparse.ArgumentParser(
        description="Delta Exchange Multi-Instrument Scanner & Liquidity Profiler"
    )
    parser.add_argument(
        "--mode",
        choices=["options-otm", "chain-scan", "multi-perp", "ws", "rest"],
        default="options-otm",
        help="Execution mode: options-otm (OTM Options Scanner), multi-perp (All 5 Perpetuals), chain-scan (Perps + 0/1/2-DTE Options), or ws/rest (Single Symbol)",
    )
    parser.add_argument(
        "--underlyings",
        default="BTC,ETH,PAXG,XAUT",
        help="Comma-separated assets for chain-scan/options-otm (default: BTC,ETH,PAXG,XAUT)",
    )
    parser.add_argument(
        "--symbols",
        default="BTCUSD,ETHUSD,SOLUSD,PAXGUSD,SLVONUSD",
        help="Comma-separated symbols for multi-perp (default: BTCUSD,ETHUSD,SOLUSD,PAXGUSD,SLVONUSD)",
    )
    parser.add_argument(
        "--symbol", default=config.SYMBOL, help=f"Single-symbol tracking (default: {config.SYMBOL})"
    )
    parser.add_argument(
        "--budget", type=float, default=config.PRIMARY_SIMULATION_USD, help="Simulation budget USD"
    )
    parser.add_argument(
        "--duration", type=int, default=300, help="Run duration in seconds (default: 300)"
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        default=None,
        help="Timed cloud run duration in minutes (e.g. 1 for testing, 300 for 5-hour evening run). Bypasses IST idle sleep.",
    )
    parser.add_argument(
        "--interval", type=float, default=5.0, help="Polling interval in seconds (default: 5.0)"
    )
    parser.add_argument(
        "--depth", type=int, default=config.DEPTH, help="Orderbook depth levels"
    )
    parser.add_argument(
        "--sink", choices=["csv", "sqlite", "both"], default="sqlite", help="Storage engine"
    )
    parser.add_argument(
        "--export-parquet",
        action="store_true",
        default=True,
        help="Export session captured rows to ZSTD Parquet via DuckDB (default: True)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    run_duration = args.duration
    if args.duration_minutes is not None:
        run_duration = args.duration_minutes * 60
        print(f"[+] Timed Cloud Mode: {args.duration_minutes}m run ({run_duration}s) | Bypassing IST idle sleep window")

    if args.mode == "options-otm":
        run_options_otm_scanner(
            underlyings_str=args.underlyings,
            duration=run_duration,
            interval=args.interval,
            sink=args.sink,
            export_parquet=args.export_parquet,
        )
    elif args.mode == "multi-perp":
        run_multi_perp_collector(
            symbols_str=args.symbols,
            duration=run_duration,
            interval=args.interval,
            depth=args.depth,
            sink=args.sink,
        )
    elif args.mode == "chain-scan":
        run_chain_scanner(
            underlyings_str=args.underlyings,
            duration=run_duration,
            interval=args.interval,
            sink=args.sink,
        )
    else:
        run_single_collector(
            symbol=args.symbol,
            budget=args.budget,
            duration=run_duration,
            interval=args.interval,
            depth=args.depth,
            sink=args.sink,
            mode=args.mode,
        )
