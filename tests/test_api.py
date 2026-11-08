
from src.delta_api import DeltaAPI


def main():
    api = DeltaAPI(timeout=10)

    print("\nConnecting to Delta Exchange...")

    try:
        product = api.get_product("BTCUSD")
        orderbook = api.get_orderbook("BTCUSD", depth=5)

        print("\nPRODUCT INFORMATION")
        print("-------------------")
        print("Symbol:", product.get("symbol"))
        print("Product ID:", product.get("id"))
        print("Contract Value:", product.get("contract_value"))

        print("\nORDER BOOK")
        print("----------")

        print("\nBEST BIDS:")
        for level in orderbook.get("buy", []):
            print(level)

        print("\nBEST ASKS:")
        for level in orderbook.get("sell", []):
            print(level)

        print("\nAPI TEST SUCCESSFUL!")

    except Exception as error:
        print("\nAPI TEST FAILED!")
        print(error)


if __name__ == "__main__":
    main()
