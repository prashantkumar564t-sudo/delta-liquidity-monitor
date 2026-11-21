"""
src/storage.py
Store raw order book snapshots and analysis metrics in CSV and SQLite WAL.
"""

import csv
import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


class CSVStorage:
    """Store raw order book snapshots and analysis metrics in CSV."""

    def __init__(self, project_root=None):
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent

        self.project_root = Path(project_root)

        self.raw_path = (
            self.project_root / "data" / "raw" / "orderbook.csv"
        )

        self.metrics_path = (
            self.project_root / "data" / "analysis" / "metrics.csv"
        )

        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)

        self.raw_fields = [
            "timestamp_utc",
            "symbol",
            "exchange_timestamp",
            "bids_json",
            "asks_json",
        ]

        self.metric_fields = [
            "timestamp_utc",
            "best_bid",
            "best_ask",
            "mid_price",
            "spread",
            "spread_percent",
            "bid_contracts",
            "ask_contracts",
            "bid_btc",
            "ask_btc",
            "bid_notional_usd",
            "ask_notional_usd",
            "imbalance",
            "buy_slippage_json",
            "sell_slippage_json",
        ]

    @staticmethod
    def _timestamp():
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _write_row(path, fields, row):
        file_exists = path.exists() and path.stat().st_size > 0

        with path.open(
            "a",
            newline="",
            encoding="utf-8"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=fields,
                extrasaction="ignore"
            )

            if not file_exists:
                writer.writeheader()

            writer.writerow(row)
            file.flush()

    def write_raw_orderbook(
        self,
        orderbook,
        symbol="BTCUSD",
        exchange_timestamp=None,
        timestamp=None
    ):
        row = {
            "timestamp_utc": timestamp or self._timestamp(),
            "symbol": symbol,
            "exchange_timestamp": exchange_timestamp,
            "bids_json": json.dumps(
                orderbook.get("buy", []),
                separators=(",", ":")
            ),
            "asks_json": json.dumps(
                orderbook.get("sell", []),
                separators=(",", ":")
            ),
        }

        self._write_row(
            self.raw_path,
            self.raw_fields,
            row
        )

    def write_metrics(
        self,
        metrics,
        slippage_results=None,
        timestamp=None
    ):
        slippage_results = slippage_results or {}

        row = {
            "timestamp_utc": timestamp or self._timestamp(),
            **metrics,
            "buy_slippage_json": json.dumps(
                slippage_results.get("buy", {}),
                default=str
            ),
            "sell_slippage_json": json.dumps(
                slippage_results.get("sell", {}),
                default=str
            ),
        }

        self._write_row(
            self.metrics_path,
            self.metric_fields,
            row
        )


class SQLiteStorage:
    """High-throughput, lossless SQLite WAL telemetry storage sink."""

    def __init__(self, db_path=None, project_root=None, batch_size=10):
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            if project_root is None:
                project_root = Path(__file__).resolve().parent.parent
            self.db_path = Path(project_root) / "data" / "telemetry.db"

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.batch_size = max(1, batch_size)

        self._snapshot_buffer = []
        self._execution_buffer = []
        self._expiry_vol_buffer = []
        self._otm_options_buffer = []

        self._conn = sqlite3.connect(str(self.db_path))
        self._init_db()

    def _init_db(self):
        """Enforce WAL mode, NORMAL sync, memory temp store, and idempotent schema."""
        cursor = self._conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA temp_store = MEMORY;")
        cursor.execute("PRAGMA cache_size = -2000;")  # 2 MB cache to preserve < 30 MB footprint

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS l2_snapshots (
                symbol TEXT NOT NULL,
                timestamp_us INTEGER NOT NULL,
                timestamp_utc TEXT NOT NULL,
                exchange_timestamp INTEGER,
                best_bid TEXT NOT NULL,
                best_ask TEXT NOT NULL,
                mid_price TEXT NOT NULL,
                spread TEXT NOT NULL,
                spread_percent TEXT NOT NULL,
                bid_contracts INTEGER NOT NULL,
                ask_contracts INTEGER NOT NULL,
                bid_btc TEXT NOT NULL,
                ask_btc TEXT NOT NULL,
                bid_notional_usd TEXT NOT NULL,
                ask_notional_usd TEXT NOT NULL,
                imbalance TEXT NOT NULL,
                rtt_latency_ns INTEGER,
                executable_buy_lots INTEGER DEFAULT 0,
                executable_sell_lots INTEGER DEFAULT 0,
                raw_bids_json TEXT NOT NULL,
                raw_asks_json TEXT NOT NULL,
                PRIMARY KEY (symbol, timestamp_us)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_simulations (
                symbol TEXT NOT NULL,
                timestamp_us INTEGER NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                requested_usd TEXT NOT NULL,
                executed_contracts INTEGER NOT NULL,
                executed_btc TEXT NOT NULL,
                executed_notional_usd TEXT NOT NULL,
                average_price TEXT NOT NULL,
                best_price TEXT NOT NULL,
                slippage_usd TEXT NOT NULL,
                slippage_percent TEXT NOT NULL,
                fee_usd TEXT NOT NULL,
                unfilled_usd TEXT NOT NULL,
                fully_executed INTEGER NOT NULL,
                levels_used INTEGER NOT NULL,
                queue_depth_ahead INTEGER,
                PRIMARY KEY (symbol, timestamp_us, side, order_type)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS expiry_liquidity_vol (
                underlying TEXT NOT NULL,
                expiry_bucket TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                timestamp_us INTEGER NOT NULL,
                timestamp_utc TEXT NOT NULL,
                spot_price TEXT NOT NULL,
                atm_strike TEXT NOT NULL,
                atm_iv_mean TEXT NOT NULL,
                straddle_premium_usd TEXT NOT NULL,
                expected_move_pct TEXT NOT NULL,
                total_ce_bid_lots INTEGER NOT NULL,
                total_ce_ask_lots INTEGER NOT NULL,
                total_pe_bid_lots INTEGER NOT NULL,
                total_pe_ask_lots INTEGER NOT NULL,
                lot_imbalance TEXT NOT NULL,
                futures_rv_pct TEXT NOT NULL,
                futures_top_lots INTEGER NOT NULL,
                PRIMARY KEY (underlying, expiry_bucket, timestamp_us)
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS otm_options_liquidity (
                timestamp_us INTEGER NOT NULL,
                datetime_ist TEXT NOT NULL,
                underlying TEXT NOT NULL,
                symbol TEXT NOT NULL,
                expiry_bucket TEXT NOT NULL,
                option_type TEXT NOT NULL,
                strike REAL NOT NULL,
                delta REAL,
                iv REAL,
                mark_price REAL NOT NULL,
                ltp REAL,
                best_bid REAL,
                best_ask REAL,
                bid_size REAL,
                ask_size REAL,
                spread_vs_mark_pct REAL,
                bid_slippage_pct REAL,
                PRIMARY KEY (symbol, timestamp_us)
            );
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_otm_underlying_ts ON otm_options_liquidity (underlying, timestamp_us);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_otm_expiry_delta ON otm_options_liquidity (expiry_bucket, delta);")
        cursor.execute("PRAGMA table_info(l2_snapshots);")
        columns = [c[1] for c in cursor.fetchall()]
        if "executable_buy_lots" not in columns:
            cursor.execute("ALTER TABLE l2_snapshots ADD COLUMN executable_buy_lots INTEGER DEFAULT 0;")
        if "executable_sell_lots" not in columns:
            cursor.execute("ALTER TABLE l2_snapshots ADD COLUMN executable_sell_lots INTEGER DEFAULT 0;")

        self._conn.commit()

    @staticmethod
    def _to_text(val):
        """Serialize numeric types to exact string representations for lossless storage."""
        if val is None:
            return ""
        return str(val)

    def write_snapshot_and_metrics(
        self,
        symbol: str,
        orderbook: dict,
        metrics: dict,
        slippage_results: dict | None = None,
        exchange_timestamp: int | None = None,
        timestamp_utc: str | None = None,
        timestamp_us: int | None = None,
        rtt_latency_ns: int | None = None
    ):
        """Buffer a complete L2 snapshot and execution simulations for batched commit."""
        now_utc = timestamp_utc or datetime.now(UTC).isoformat()
        now_us = timestamp_us if timestamp_us is not None else int(time.time() * 1_000_000)

        snapshot_row = (
            symbol,
            now_us,
            now_utc,
            exchange_timestamp,
            self._to_text(metrics.get("best_bid")),
            self._to_text(metrics.get("best_ask")),
            self._to_text(metrics.get("mid_price")),
            self._to_text(metrics.get("spread")),
            self._to_text(metrics.get("spread_percent")),
            int(metrics.get("bid_contracts", 0)),
            int(metrics.get("ask_contracts", 0)),
            self._to_text(metrics.get("bid_btc")),
            self._to_text(metrics.get("ask_btc")),
            self._to_text(metrics.get("bid_notional_usd")),
            self._to_text(metrics.get("ask_notional_usd")),
            self._to_text(metrics.get("imbalance")),
            rtt_latency_ns,
            int(metrics.get("max_executable_buy_lots", 0)),
            int(metrics.get("max_executable_sell_lots", 0)),
            json.dumps(orderbook.get("buy", []), separators=(",", ":")),
            json.dumps(orderbook.get("sell", []), separators=(",", ":")),
        )
        self._snapshot_buffer.append(snapshot_row)

        if slippage_results:
            for side, sim in slippage_results.items():
                if not sim:
                    continue
                order_type = sim.get("order_type", "taker")
                exec_row = (
                    symbol,
                    now_us,
                    side,
                    order_type,
                    self._to_text(sim.get("requested_usd")),
                    int(sim.get("executed_contracts", 0)),
                    self._to_text(sim.get("executed_btc")),
                    self._to_text(sim.get("executed_notional_usd")),
                    self._to_text(sim.get("average_execution_price")),
                    self._to_text(sim.get("best_price")),
                    self._to_text(sim.get("slippage_usd")),
                    self._to_text(sim.get("slippage_percent")),
                    self._to_text(sim.get("taker_fee_usd", sim.get("fee_usd"))),
                    self._to_text(sim.get("unfilled_usd")),
                    1 if sim.get("fully_executed") else 0,
                    int(sim.get("levels_used", 0)),
                    sim.get("queue_depth_ahead")
                )
                self._execution_buffer.append(exec_row)

        if len(self._snapshot_buffer) >= self.batch_size:
            self.flush()

    def write_expiry_liquidity_vol(
        self,
        underlying: str,
        expiry_bucket: str,
        expiry_date: str,
        spot_price: Decimal,
        atm_strike: Decimal,
        atm_iv_mean: Decimal,
        straddle_premium_usd: Decimal,
        expected_move_pct: Decimal,
        total_ce_bid_lots: int,
        total_ce_ask_lots: int,
        total_pe_bid_lots: int,
        total_pe_ask_lots: int,
        lot_imbalance: Decimal,
        futures_rv_pct: Decimal,
        futures_top_lots: int,
        timestamp_utc: str | None = None,
        timestamp_us: int | None = None,
    ):
        """Buffer options volatility and lot liquidity metrics by expiry bucket."""
        now_utc = timestamp_utc or datetime.now(UTC).isoformat()
        now_us = timestamp_us if timestamp_us is not None else int(time.time() * 1_000_000)

        row = (
            underlying,
            expiry_bucket,
            expiry_date,
            now_us,
            now_utc,
            self._to_text(spot_price),
            self._to_text(atm_strike),
            self._to_text(atm_iv_mean),
            self._to_text(straddle_premium_usd),
            self._to_text(expected_move_pct),
            int(total_ce_bid_lots),
            int(total_ce_ask_lots),
            int(total_pe_bid_lots),
            int(total_pe_ask_lots),
            self._to_text(lot_imbalance),
            self._to_text(futures_rv_pct),
            int(futures_top_lots),
        )
        self._expiry_vol_buffer.append(row)

        if len(self._expiry_vol_buffer) >= self.batch_size:
            self.flush()

    def write_otm_options_liquidity(
        self,
        records: list,
        timestamp_us: int | None = None,
        datetime_ist: str | None = None,
    ):
        """Buffer live OTM options liquidity records for batched SQLite commit."""
        if not records:
            return

        now_us = timestamp_us if timestamp_us is not None else int(time.time() * 1_000_000)
        if datetime_ist is None:
            ist_dt = datetime.now(timezone(timedelta(hours=5, minutes=30)))
            now_ist = ist_dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            now_ist = datetime_ist

        for r in records:
            ts_us = r.get("timestamp_us") or now_us
            dt_ist = r.get("datetime_ist") or now_ist
            row = (
                int(ts_us),
                str(dt_ist),
                str(r.get("underlying", "")),
                str(r.get("symbol", "")),
                str(r.get("expiry_bucket", "")),
                str(r.get("option_type", "")),
                float(r.get("strike", 0.0)),
                float(r["delta"]) if r.get("delta") is not None else None,
                float(r["iv"]) if r.get("iv") is not None else None,
                float(r.get("mark_price", 0.0)),
                float(r["ltp"]) if r.get("ltp") is not None else None,
                float(r.get("best_bid", 0.0)),
                float(r.get("best_ask", 0.0)),
                float(r.get("bid_size", 0.0)),
                float(r.get("ask_size", 0.0)),
                float(r.get("spread_vs_mark_pct", 0.0)),
                float(r.get("bid_slippage_pct", 0.0)),
            )
            self._otm_options_buffer.append(row)

        if len(self._otm_options_buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        """Execute batched executemany insert with transaction commit."""
        if (
            not self._snapshot_buffer
            and not self._execution_buffer
            and not self._expiry_vol_buffer
            and not self._otm_options_buffer
        ):
            return

        cursor = self._conn.cursor()
        if self._snapshot_buffer:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO l2_snapshots (
                    symbol, timestamp_us, timestamp_utc, exchange_timestamp,
                    best_bid, best_ask, mid_price, spread, spread_percent,
                    bid_contracts, ask_contracts, bid_btc, ask_btc,
                    bid_notional_usd, ask_notional_usd, imbalance,
                    rtt_latency_ns, executable_buy_lots, executable_sell_lots,
                    raw_bids_json, raw_asks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                self._snapshot_buffer
            )
            self._snapshot_buffer.clear()

        if self._execution_buffer:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO execution_simulations (
                    symbol, timestamp_us, side, order_type, requested_usd,
                    executed_contracts, executed_btc, executed_notional_usd,
                    average_price, best_price, slippage_usd, slippage_percent,
                    fee_usd, unfilled_usd, fully_executed, levels_used,
                    queue_depth_ahead
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                self._execution_buffer
            )
            self._execution_buffer.clear()

        if self._expiry_vol_buffer:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO expiry_liquidity_vol (
                    underlying, expiry_bucket, expiry_date, timestamp_us, timestamp_utc,
                    spot_price, atm_strike, atm_iv_mean, straddle_premium_usd, expected_move_pct,
                    total_ce_bid_lots, total_ce_ask_lots, total_pe_bid_lots, total_pe_ask_lots,
                    lot_imbalance, futures_rv_pct, futures_top_lots
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                self._expiry_vol_buffer
            )
            self._expiry_vol_buffer.clear()

        if self._otm_options_buffer:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO otm_options_liquidity (
                    timestamp_us, datetime_ist, underlying, symbol, expiry_bucket,
                    option_type, strike, delta, iv, mark_price, ltp,
                    best_bid, best_ask, bid_size, ask_size,
                    spread_vs_mark_pct, bid_slippage_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                self._otm_options_buffer
            )
            self._otm_options_buffer.clear()

        self._conn.commit()

    def close(self):
        """Flush remaining buffered rows and close connection."""
        self.flush()
        if self._conn:
            self._conn.close()
            self._conn = None

    def export_session_to_parquet(
        self,
        session_start_us: int | None = None,
        export_dir: Path | str | None = None,
        session_dt_ist: datetime | None = None,
        table_name: str | None = None,
    ) -> dict:
        """Export session rows to ZSTD-compressed Parquet via DuckDB."""
        self.flush()
        return export_session_to_parquet(
            db_path=self.db_path,
            session_start_us=session_start_us,
            export_dir=export_dir,
            session_dt_ist=session_dt_ist,
            table_name=table_name,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def export_session_to_parquet(
    db_path: Path | str | None = None,
    session_start_us: int | None = None,
    export_dir: Path | str | None = None,
    session_dt_ist: datetime | None = None,
    table_name: str | None = None,
) -> dict:
    """
    Export session's captured rows from SQLite to ZSTD-compressed Parquet via DuckDB.
    
    Target format: ./exports/delta_evening_YYYYMMDD_HHMM_IST.parquet
    """
    import duckdb

    if db_path is None:
        db_path = Path(__file__).resolve().parent.parent / "data" / "telemetry.db"
    db_path = Path(db_path)

    if export_dir is None:
        export_dir = Path(__file__).resolve().parent.parent / "exports"
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    if session_dt_ist is None:
        ist = timezone(timedelta(hours=5, minutes=30))
        session_dt_ist = datetime.now(ist)

    timestamp_str = session_dt_ist.strftime("%Y%m%d_%H%M_IST")
    export_path = export_dir / f"delta_evening_{timestamp_str}.parquet"

    db_str = str(db_path.resolve()).replace("\\", "/")
    out_str = str(export_path.resolve()).replace("\\", "/")

    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{db_str}' AS sqlite_db (TYPE SQLITE)")

        # Determine target table if not specified
        if table_name is None:
            candidates = ["otm_options_liquidity", "l2_snapshots", "expiry_liquidity_vol"]
            table_name = "otm_options_liquidity"
            for cand in candidates:
                try:
                    where_q = f"WHERE timestamp_us >= {int(session_start_us)}" if session_start_us else ""
                    cnt = con.execute(f"SELECT count(*) FROM sqlite_db.{cand} {where_q}").fetchone()[0]
                    if cnt > 0:
                        table_name = cand
                        break
                except Exception:
                    pass

        where_sql = f"WHERE timestamp_us >= {int(session_start_us)}" if session_start_us else ""
        count_res = con.execute(f"SELECT count(*) FROM sqlite_db.{table_name} {where_sql}").fetchone()
        row_count = count_res[0] if count_res else 0

        # Export table to Parquet with ZSTD compression
        query = f"SELECT * FROM sqlite_db.{table_name} {where_sql}"
        con.execute(f"COPY ({query}) TO '{out_str}' (FORMAT PARQUET, COMPRESSION ZSTD)")

    finally:
        con.close()

    file_size = export_path.stat().st_size if export_path.exists() else 0
    return {
        "export_path": str(export_path),
        "filename": export_path.name,
        "row_count": row_count,
        "file_size_bytes": file_size,
        "file_size_kb": round(file_size / 1024, 2),
        "table_name": table_name,
    }
