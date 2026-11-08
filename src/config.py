"""
src/config.py
Configuration parameters for Delta Liquidity Monitor.
"""

# Market Parameters
SYMBOL = "BTCUSD"
DEPTH = 20                 # आर्डर बुक डेप्थ (स्लिपेज के लिए 20 बेहतर है)
CONTRACT_VALUE = 0.001     # 1 contract = 0.001 BTC
TAKER_FEE = 0.0005         # 0.05% taker fee

# Execution / Simulation Parameters
ORDER_SIZES_USD = [100.0, 500.0, 1000.0, 5000.0]  # टेस्ट बजट (USD)
PRIMARY_SIMULATION_USD = 10000.0                    # मुख्य मेट्रिक्स के लिए USD

# Data Collection Schedule
SNAPSHOT_INTERVAL = 1.0    # 1 snapshot प्रति सेकंड
COLLECTION_DURATION = 300  # 300 सेकंड (5 मिनट)

# API
API_TIMEOUT = 5