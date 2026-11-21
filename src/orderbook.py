"""
src/orderbook.py
Analyze Delta Exchange Level 2 order book snapshots with pure Decimal financial precision
and lot-level executable depth under configurable slippage bounds.
"""

from decimal import Decimal


class OrderBookAnalyzer:
    """Analyze Delta Exchange Level 2 order book snapshots with Decimal precision."""

    def __init__(self, contract_value=0.001):
        self.contract_value = Decimal(str(contract_value))

    def compute_executable_lots(
        self,
        orderbook: dict,
        max_slippage_pct: Decimal = Decimal("0.0010")  # 0.10% maximum slippage
    ) -> dict:
        """
        Compute maximum executable buy and sell lots within a strict slippage threshold.
        Buy orders walk asks up to best_ask * (1 + max_slippage_pct).
        Sell orders walk bids down to best_bid * (1 - max_slippage_pct).
        """
        bids = orderbook.get("buy", [])
        asks = orderbook.get("sell", [])

        if not bids or not asks:
            return {"max_executable_buy_lots": 0, "max_executable_sell_lots": 0}

        best_ask = Decimal(str(asks[0]["price"]))
        best_bid = Decimal(str(bids[0]["price"]))

        max_ask_price = best_ask * (Decimal(1) + max_slippage_pct)
        min_bid_price = best_bid * (Decimal(1) - max_slippage_pct)

        executable_buy_lots = sum(
            int(level["size"]) for level in asks
            if Decimal(str(level["price"])) <= max_ask_price
        )

        executable_sell_lots = sum(
            int(level["size"]) for level in bids
            if Decimal(str(level["price"])) >= min_bid_price
        )

        return {
            "max_executable_buy_lots": executable_buy_lots,
            "max_executable_sell_lots": executable_sell_lots,
            "max_slippage_pct": max_slippage_pct,
        }

    def analyze(self, orderbook, max_slippage_pct: Decimal = Decimal("0.0010")):
        bids = orderbook.get("buy", [])
        asks = orderbook.get("sell", [])

        if not bids or not asks:
            raise ValueError("Order book is missing bid or ask levels")

        best_bid = Decimal(str(bids[0]["price"]))
        best_ask = Decimal(str(asks[0]["price"]))

        if best_bid <= 0 or best_ask <= 0:
            raise ValueError("Invalid order book prices")

        if best_ask <= best_bid:
            raise ValueError("Crossed or zero-spread order book detected")

        mid_price = (best_bid + best_ask) / Decimal(2)
        spread = best_ask - best_bid
        spread_percent = (spread / mid_price) * Decimal(100)

        bid_contracts = sum(int(level["size"]) for level in bids)
        ask_contracts = sum(int(level["size"]) for level in asks)

        bid_btc = Decimal(str(bid_contracts)) * self.contract_value
        ask_btc = Decimal(str(ask_contracts)) * self.contract_value

        bid_notional = bid_btc * best_bid
        ask_notional = ask_btc * best_ask

        total_depth = bid_contracts + ask_contracts

        imbalance = (
            Decimal(str(bid_contracts - ask_contracts)) / Decimal(str(total_depth))
            if total_depth else Decimal(0)
        )

        executable_info = self.compute_executable_lots(orderbook, max_slippage_pct=max_slippage_pct)

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
            "max_executable_buy_lots": executable_info["max_executable_buy_lots"],
            "max_executable_sell_lots": executable_info["max_executable_sell_lots"],
        }
