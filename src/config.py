"""
src/config.py
Configuration parameters for Delta Liquidity Monitor.
"""

from datetime import datetime, time, timedelta, timezone

# Market Parameters
SYMBOL = "BTCUSD"
DEPTH = 20                 # L2 Order book depth levels
CONTRACT_VALUE = 0.001     # 1 contract = 0.001 BTC
TAKER_FEE = 0.0005         # 0.05% taker fee
MAKER_FEE = 0.0002         # 0.02% maker fee

# Multi-Asset Configuration
UNDERLYINGS = ("BTC", "ETH", "PAXG", "XAUT")
DEFAULT_PERP_SYMBOLS = ("BTCUSD", "ETHUSD", "SOLUSD", "PAXGUSD", "XAUTUSD", "SLVONUSD")

# Execution / Simulation Parameters
ORDER_SIZES_USD = [100.0, 500.0, 1000.0, 5000.0]  # Test budgets (USD)
PRIMARY_SIMULATION_USD = 10000.0                    # Primary simulation budget (USD)

# Data Collection Schedule
SNAPSHOT_INTERVAL = 1.0    # 1 snapshot per second
COLLECTION_DURATION = 300  # 300 seconds (5 minutes)

# REST & WebSocket Endpoints
API_TIMEOUT = 5
WS_URL = "wss://socket.india.delta.exchange"
WS_TIMEOUT_SECONDS = 3.0   # REST fallback threshold if no WS tick within 3s

# High-Frequency IST Trading Windows for Daemon
# Formats: (start_time, end_time, label)
IST = timezone(timedelta(hours=5, minutes=30))
DAEMON_IST_WINDOWS = [
    (time(9, 30), time(9, 45), "Morning Entry Window (09:35 IST Strangle)"),
    (time(9, 45), time(10, 30), "Morning Momentum Window"),
    (time(13, 30), time(13, 45), "Mid-Day Window"),
    (time(16, 45), time(17, 25), "Evening Exit & Expiry Window"),
    (time(17, 0), time(22, 0), "5-Hour Evening Cloud Run Window"),
]


def is_in_ist_window(current_dt: datetime | None = None) -> tuple[bool, str]:
    """Check if the provided datetime (or now in IST) falls within an active trading window."""
    now_ist = current_dt or datetime.now(IST)
    curr_time = now_ist.time()
    for start, end, label in DAEMON_IST_WINDOWS:
        if start <= curr_time <= end:
            return True, label
    return False, "Idle Period"
