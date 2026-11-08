
from decimal import Decimal, ROUND_FLOOR


class SlippageCalculator:
    """Simulate market execution with a strict USD budget."""

    def __init__(self, contract_value=0.001, taker_fee=0.0005):
        self.contract_value = Decimal(str(contract_value))
        self.taker_fee = Decimal(str(taker_fee))

    def simulate(self, orderbook, order_usd, side="buy"):
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
        executed_notional = Decimal("0")
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

        slippage_percent = slippage / best_price * 100
        fee = executed_notional * self.taker_fee

        return {
            "side": side,
            "requested_usd": budget,
            "executed_contracts": executed_contracts,
            "executed_btc": executed_contracts * self.contract_value,
            "executed_notional_usd": executed_notional,
            "average_execution_price": average_price,
            "best_price": best_price,
            "slippage_usd": slippage,
            "slippage_percent": slippage_percent,
            "taker_fee_usd": fee,
            "unfilled_usd": remaining_usd,
            "fully_executed": remaining_usd == 0,
            "levels_used": executed_levels,
        }
