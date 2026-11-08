
from src.orderbook import OrderBookAnalyzer


def main():
    analyzer = OrderBookAnalyzer(contract_value=0.001)

    sample_orderbook = {
        "buy": [
            {"price": "100", "size": 10},
            {"price": "99.5", "size": 20},
        ],
        "sell": [
            {"price": "100.5", "size": 15},
            {"price": "101", "size": 25},
        ],
    }

    result = analyzer.analyze(sample_orderbook)

    print("\nORDER BOOK ANALYSIS")
    print("-------------------")

    for key, value in result.items():
        print(f"{key}: {value}")

    assert result["spread"] == 0.5
    assert result["mid_price"] == 100.25
    assert result["bid_contracts"] == 30
    assert result["ask_contracts"] == 40

    print("\nORDER BOOK TEST PASSED!")


if __name__ == "__main__":
    main()
