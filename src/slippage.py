from decimal import ROUND_FLOOR, Decimal


class SlippageCalculator:
    """Simulate market execution and passive maker queue positions."""

    def __init__(self, contract_value=0.001, taker_fee=0.0005, maker_fee=0.0002):
        self.contract_value = Decimal(str(contract_value))
        self.taker_fee = Decimal(str(taker_fee))
        self.maker_fee = Decimal(str(maker_fee))

    def simulate(self, orderbook, order_usd, side="buy"):
        """Simulate aggressive market (taker) execution walking the order book ladder."""
        budget = Decimal(str(order_usd))

        if budget <= 0:
            raise ValueError("Order size must be greater than zero")

        if side not in ("buy", "sell"):
            raise ValueError("Side must be 'buy' or 'sell'")

        levels = orderbook.get(
            "sell" if side == "buy" else "buy", []
        )

        if not levels:
            raise ValueError("Order book side is empty")

        best_price = Decimal(str(levels[0]["price"]))

        if best_price <= 0:
            raise ValueError("Invalid best price")

        remaining_usd = budget
        executed_contracts = 0
        executed_notional = Decimal(0)
        executed_levels = 0

        for level in levels:
            price = Decimal(str(level["price"]))
            available = int(level["size"])

            if price <= 0 or available < 0:
                raise ValueError("Invalid order book level")

            contract_notional = price * self.contract_value

            affordable = int(
                (remaining_usd / contract_notional).to_integral_value(
                    rounding=ROUND_FLOOR
                )
            )

            fill = min(available, affordable)

            if fill <= 0:
                continue

            fill_notional = fill * contract_notional

            executed_contracts += fill
            executed_notional += fill_notional
            remaining_usd -= fill_notional
            executed_levels += 1

            if remaining_usd == 0:
                break

        if executed_contracts == 0:
            raise ValueError("No contracts affordable or available")

        average_price = (
            executed_notional /
            (executed_contracts * self.contract_value)
        )

        if side == "buy":
            slippage = average_price - best_price
        else:
            slippage = best_price - average_price

        slippage_percent = (slippage / best_price) * Decimal(100)
        fee = executed_notional * self.taker_fee

        return {
            "side": side,
            "order_type": "taker",
            "requested_usd": budget,
            "executed_contracts": executed_contracts,
            "executed_btc": executed_contracts * self.contract_value,
            "executed_notional_usd": executed_notional,
            "average_execution_price": average_price,
            "best_price": best_price,
            "slippage_usd": slippage,
            "slippage_percent": slippage_percent,
            "taker_fee_usd": fee,
            "fee_usd": fee,
            "unfilled_usd": remaining_usd,
            "fully_executed": remaining_usd == 0,
            "levels_used": executed_levels,
            "queue_depth_ahead": None,
        }

    def simulate_maker(self, orderbook, limit_price, size_contracts, side="buy", maker_fee=None):
        """
        Simulate passive limit order (maker) placement and estimate queue position.
        
        Calculates FIFO queue contracts ahead at and above/below the limit price.
        Enforces that passive orders do not cross the opposite best quote.
        """
        price = Decimal(str(limit_price))
        contracts = int(size_contracts)
        effective_maker_fee = self.maker_fee if maker_fee is None else Decimal(str(maker_fee))

        if price <= 0:
            raise ValueError("Limit price must be greater than zero")

        if contracts <= 0:
            raise ValueError("Size in contracts must be greater than zero")

        if side not in ("buy", "sell"):
            raise ValueError("Side must be 'buy' or 'sell'")

        bids = orderbook.get("buy", [])
        asks = orderbook.get("sell", [])

        if not bids or not asks:
            raise ValueError("Order book is missing bid or ask levels")

        best_bid = Decimal(str(bids[0]["price"]))
        best_ask = Decimal(str(asks[0]["price"]))

        # Passive invariant: limit order must not cross the spread (would be taker execution)
        if side == "buy":
            if price >= best_ask:
                raise ValueError(
                    f"Limit buy price ({price}) crosses best ask ({best_ask}); executes as taker"
                )
            target_side_levels = bids
            best_target_price = best_bid
        else:
            if price <= best_bid:
                raise ValueError(
                    f"Limit sell price ({price}) crosses best bid ({best_bid}); executes as taker"
                )
            target_side_levels = asks
            best_target_price = best_ask

        # Calculate FIFO queue depth ahead
        # Any existing orders with better price priority, plus existing orders at same price level
        queue_depth_ahead = 0
        for level in target_side_levels:
            lvl_price = Decimal(str(level["price"]))
            lvl_size = int(level["size"])

            if side == "buy":
                if lvl_price > price:
                    queue_depth_ahead += lvl_size
                elif lvl_price == price:
                    queue_depth_ahead += lvl_size
                    break
            else:  # sell
                if lvl_price < price:
                    queue_depth_ahead += lvl_size
                elif lvl_price == price:
                    queue_depth_ahead += lvl_size
                    break

        notional_usd = price * contracts * self.contract_value
        fee_usd = notional_usd * effective_maker_fee

        return {
            "side": side,
            "order_type": "maker",
            "limit_price": price,
            "requested_usd": notional_usd,
            "executed_contracts": contracts,
            "executed_btc": contracts * self.contract_value,
            "executed_notional_usd": notional_usd,
            "average_execution_price": price,
            "best_price": best_target_price,
            "slippage_usd": Decimal(0),
            "slippage_percent": Decimal(0),
            "maker_fee_usd": fee_usd,
            "fee_usd": fee_usd,
            "unfilled_usd": Decimal(0),
            "fully_executed": True,
            "levels_used": 1,
            "queue_depth_ahead": queue_depth_ahead,
        }
