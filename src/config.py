"""
src/config.py
Configuration parameters for Delta Liquidity Monitor.
"""

# Market Parameters
SYMBOL = "BTCUSD"
DEPTH = 20                 # L2 Order book depth levels
CONTRACT_VALUE = 0.001     # 1 contract = 0.001 BTC
TAKER_FEE = 0.0005         # 0.05% taker fee
MAKER_FEE = 0.0002         # 0.02% maker fee

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
