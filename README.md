# Delta Exchange BTC Liquidity Monitor & Profiler

A lightweight, zero-dependency market liquidity and Level-2 order book telemetry engine for Delta Exchange BTC-USD perpetual contracts.

Engineered with Python Standard Library only, it captures high-frequency order book snapshots, models market impact & execution slippage across capital tiers, and continuously profiles memory utilization.

---

## Key Features

- **Zero External Dependencies**: Operates strictly on Python's built-in libraries (`urllib`, `ctypes`, `csv`, `json`, `time`, `pathlib`).
- **High-Frequency Snapshotting**: Sub-second REST polling with deterministic time-drift correction.
- **Microstructure Telemetry**:
  - Tight tick spread analysis and bid/ask contract depth.
  - Real-time order book imbalance index ($[-1.0, +1.0]$) to gauge directional order flow pressure.
- **Strict Budget Execution Modeling**: Multi-level ladder walking simulator calculating effective fill prices, nominal slippage, and taker fees.
- **Isolated Resource Profiling**: Concurrently tracks Python process RAM and working set memory with zero external profiling overhead (<27 MB RAM footprint).

---

## Live Benchmark & Production Results

Tested under live market conditions on Delta Exchange (`BTCUSD`):

| Metric | Measured Value | Remarks |
| :--- | :--- | :--- |
| **Duration / Frequency** | 300 Snapshots (1 req/sec) | 0% packet loss / 0 errors |
| **Tick Spread** | $0.50 (0.000658%) | Persistent at exchange minimum tick |
| **Passive Liquidity Depth** | ~$35M Bids vs ~$25M Asks | Highly liquid Level-2 book |
| **Order Flow Imbalance** | `+0.1447` to `+0.3426` | Confirmed bullish drift (+$18.50 and +$7.00 runs) |
| **Process RAM Footprint** | **25.75 MB - 26.46 MB** | Deterministic memory profile, zero leaks |

---

## Project Architecture

```text
delta-liquidity-monitor/
├── src/
│   ├── config.py           # Runtime hyperparameters & execution sizes
│   ├── delta_api.py        # Native HTTP client with error handling
│   ├── orderbook.py        # Microstructure & imbalance evaluator
│   ├── slippage.py         # Order execution & price impact ladder simulator
│   ├── storage.py          # Dual CSV sink (Raw + Processed Metrics)
│   └── main.py             # Event collection loop
├── monitor/
│   └── ram_monitor.py      # Win32/POSIX OS memory profiler
├── data/
│   ├── raw/                # L2 raw snapshots (bids/asks JSON)
│   └── analysis/           # Processed market metrics CSV
├── logs/                   # System memory telemetry
├── generate_report.py      # Automated report generation
└── launcher.py             # Process coordinator