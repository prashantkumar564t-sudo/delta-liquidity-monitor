
class OrderBookAnalyzer:
    """Analyze Delta Exchange Level 2 order book snapshots."""

    def __init__(self, contract_value=0.001):
        self.contract_value = contract_value

    def analyze(self, orderbook):
        bids = orderbook.get("buy", [])
        asks = orderbook.get("sell", [])

        if not bids or not asks:
            raise ValueError("Order book is missing bid or ask levels")

        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])

        if best_bid <= 0 or best_ask <= 0:
            raise ValueError("Invalid order book prices")

        mid_price = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        spread_percent = (spread / mid_price) * 100

        bid_contracts = sum(
            int(level["size"]) for level in bids
        )

        ask_contracts = sum(
            int(level["size"]) for level in asks
        )

        bid_btc = bid_contracts * self.contract_value
        ask_btc = ask_contracts * self.contract_value

        bid_notional = bid_btc * best_bid
        ask_notional = ask_btc * best_ask

        total_depth = bid_contracts + ask_contracts

        imbalance = (
            (bid_contracts - ask_contracts) / total_depth
            if total_depth else 0
        )

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid_price,
            "spread": spread,
            "spread_percent": spread_percent,
            "bid_contracts": bid_contracts,
            "ask_contracts": ask_contracts,
            "bid_btc": bid_btc,
            "ask_btc": ask_btc,
            "bid_notional_usd": bid_notional,
            "ask_notional_usd": ask_notional,
            "imbalance": imbalance,
        }
