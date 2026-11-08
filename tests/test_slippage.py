
from src.slippage import SlippageCalculator


def main():
    calculator = SlippageCalculator(
        contract_value=0.001,
        taker_fee=0.0005
    )

    sample_orderbook = {
        "buy": [
            {"price": "100", "size": 10},
            {"price": "99.5", "size": 20},
        ],
        "sell": [
            {"price": "100.5", "size": 10},
            {"price": "101", "size": 20},
            {"price": "101.5", "size": 30},
        ],
    }

    for side in ("buy", "sell"):
        result = calculator.simulate(
            sample_orderbook,
            order_usd=2.05,
            side=side
        )

        print(f"\n{side.upper()} ORDER SIMULATION")
        print("--------------------")

        for key, value in result.items():
            print(f"{key}: {value}")

        assert result["executed_contracts"] == 20
        assert result["executed_notional_usd"] <= 2.05
        assert result["unfilled_usd"] >= 0

        assert (
            result["executed_notional_usd"]
            + result["unfilled_usd"]
            == result["requested_usd"]
        )

    print("\nSLIPPAGE ACCURACY TEST PASSED!")


if __name__ == "__main__":
    main()
