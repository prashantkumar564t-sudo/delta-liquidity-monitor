# Delta Liquidity Monitor

A lightweight Python-based market liquidity and order book analysis tool for Delta Exchange BTC Perpetual Futures.

The project collects real-time order book snapshots using the Delta Exchange REST API, analyzes market liquidity, and simulates order execution to estimate slippage.

It also includes an independent system resource monitor to track the Python collector's RAM and CPU usage.

## Features

- Real-time BTC Perpetual Futures market data.
- REST API-based order book snapshots.
- Configurable snapshot interval.
- Bid and Ask order book depth analysis.
- Market spread and liquidity calculations.
- Simulated order execution at different order sizes.
- Slippage estimation.
- CSV-based raw data storage.
- Separate CSV analysis reports.
- Independent RAM and CPU monitoring.
- Lightweight architecture using Python Standard Library only.

## Project Structure

```text
delta-liquidity-monitor/
│
├── src/
│   ├── main.py
│   ├── delta_api.py
│   ├── orderbook.py
│   ├── slippage.py
│   ├── storage.py
│   └── config.py
│
├── monitor/
│   └── ram_monitor.py
│
├── data/
│   ├── raw/
│   └── analysis/
│
├── logs/
├── tests/
│
├── launcher.py
├── README.md
├── .gitignore
├── requirements.txt
└── LICENSE
```

## Requirements

- Python 3.10 or newer.
- Internet connection.
- Delta Exchange API access.

No external Python packages are required.

## Data Collection

The initial testing configuration:

- Market: BTC Perpetual Futures.
- Data source: Delta Exchange REST API.
- Snapshot interval: 1 second.
- Collection duration: 5 minutes.
- Raw data format: CSV.
- Analysis output: CSV.

## Analysis

The system will evaluate:

- Best Bid and Best Ask.
- Bid and Ask depth.
- Market spread.
- Available liquidity.
- Simulated order execution.
- Average execution price.
- Estimated slippage.

## Resource Monitoring

A separate Python process monitors:

- Collector RAM usage.
- Peak RAM consumption.
- CPU usage.
- Runtime.

## Data Storage

- `data/raw/` - Raw order book snapshots.
- `data/analysis/` - Calculated market metrics.
- `logs/` - Runtime and error logs.

Generated data and logs are excluded from Git tracking.

## Development Status

**Status: Initial Development**

This project is currently under development. Features and implementation details may change.

## License

MIT License.
