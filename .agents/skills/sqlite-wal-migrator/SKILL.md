---
name: sqlite-wal-migrator
description: Enforces SQLite WAL mode, NORMAL synchronous pragma, batched executemany writes, and idempotent composite primary keys for quantitative telemetry.
---

# SQLite WAL Migrator

This skill governs high-throughput, low-latency telemetry storage using Python's native `sqlite3` engine.

## 1. Engine Configuration & Pragmas
All SQLite database connections opened for ingestion or analysis must execute the following performance and durability pragmas immediately after opening:
```python
import sqlite3

def init_db(connection: sqlite3.Connection):
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA temp_store = MEMORY;")
    cursor.execute("PRAGMA cache_size = -64000;")  # 64 MB cache
    connection.commit()
```

## 2. Idempotent Schema Design
Tables must enforce strict composite primary keys or uniqueness constraints to prevent duplicate ticks during reconnects:
```sql
CREATE TABLE IF NOT EXISTS l2_snapshots (
    symbol TEXT NOT NULL,
    timestamp_us INTEGER NOT NULL,
    exchange_timestamp INTEGER,
    best_bid TEXT NOT NULL,
    best_ask TEXT NOT NULL,
    mid_price TEXT NOT NULL,
    spread TEXT NOT NULL,
    bid_contracts INTEGER NOT NULL,
    ask_contracts INTEGER NOT NULL,
    imbalance TEXT NOT NULL,
    raw_bids_json TEXT NOT NULL,
    raw_asks_json TEXT NOT NULL,
    PRIMARY KEY (symbol, timestamp_us)
);
```

## 3. Batched Writes (`executemany`)
- Never execute single-row `INSERT` statements in a tight polling loop with individual commits.
- Buffer snapshots in a lightweight local buffer (e.g. 5–20 rows or periodic flushes) and persist using `cursor.executemany("INSERT OR IGNORE INTO ...", batch)`.
- Explicitly commit and handle database locked errors with exponential backoff.
