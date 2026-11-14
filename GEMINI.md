# Project Governance & Quantitative Engineering Guidelines
# Delta Exchange BTC Liquidity Monitor & Profiler

## 1. Zero External Dependencies
- **Strict Standard Library Only:** All application code must strictly utilize modules from the Python Standard Library:
  - `urllib.request`, `urllib.error`, `json` (REST API interactions)
  - `asyncio`, `ssl`, `socket` (High-frequency WebSocket protocol implementations)
  - `sqlite3` (Embedded transactional telemetry storage)
  - `decimal` (Financial calculations and arithmetic invariants)
  - `ctypes`, `os`, `sys`, `time` (Operating system telemetry and clock synchronization)
  - `pathlib` (OS-agnostic file system paths)
  - `argparse` (CLI ergonomics and execution parameters)
  - `unittest` (Regression testing and verification)
- **Strict Prohibition:** Never introduce, import, or recommend third-party packages such as `pandas`, `numpy`, `requests`, `websockets`, `aiohttp`, or `psutil`.

## 2. Financial Precision & Microstructure Invariants
- **Decimal Representation:** All prices, quantities, contract sizes, notional volumes, fees, and slippage metrics must be instantiated and calculated using `decimal.Decimal`.
- **Prohibition of Floats in Finance:** Floating-point representations (`float`) are strictly prohibited in financial order book pricing and order execution pipelines due to binary IEEE-754 precision loss.
- **Tick-Size & Lot Alignment:** Order book levels for `BTCUSD` must adhere to exchange tick increments ($0.50 minimum tick) and contract lot value (0.001 BTC per contract).
- **Core Market Invariants:**
  - Strict Level-2 Spread Non-Negativity: `best_ask > best_bid` (Crossed or zero spreads must trigger immediate validation errors).
  - Imbalance Normalization: Order flow imbalance must strictly lie in the closed interval `[-1.0, 1.0]`.
  - Budget Preservation: For any simulated market order, `executed_notional + unfilled_usd == requested_budget`.

## 3. Cross-Platform Portability (Windows 11 & Termux/Android)
- **Path Abstraction:** Never use hardcoded slash styles (`\` or `/`). All filesystem references must use `pathlib.Path`.
- **System Memory Profiling Fallbacks:**
  - On Windows (`nt`): Query working set memory using Win32 API via `ctypes` (`K32GetProcessMemoryInfo` / `OpenProcess`).
  - On Linux / Android Termux (`posix`): Query memory footprint via `/proc/{pid}/status` (`VmRSS`) or Python's standard `resource` module.
- **Console & Terminal Compatibility:** Avoid ANSI escape codes or platform-specific terminal features that break either Windows PowerShell or Android Termux VT-100 emulators.

## 4. Memory & Performance Discipline
- **Memory Footprint Ceiling:** Working set RAM usage of any long-running monitoring process must remain strictly below **30 MB**.
- **No In-Memory Telemetry Accumulation:** Avoid holding historical ticks or unbounded snapshots in memory lists. Stream all metrics immediately to disk sinks (SQLite WAL / CSV).
- **Time Drift Correction:** Polling loops must compute loop processing duration and sleep only the remaining delta (`max(0.0, interval - elapsed)`).
