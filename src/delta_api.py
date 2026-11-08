
import json
import urllib.request
import urllib.error


class DeltaAPI:
    """Lightweight Delta Exchange REST API client."""

    BASE_URL = "https://api.india.delta.exchange"

    def __init__(self, timeout=10):
        self.timeout = timeout

    def _get(self, endpoint):
        """Send a public GET request and return parsed JSON."""

        url = f"{self.BASE_URL}{endpoint}"

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Delta-Liquidity-Monitor/1.0",
                "Accept": "application/json",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout
            ) as response:

                status_code = response.status
                raw_data = response.read()

                if status_code != 200:
                    raise RuntimeError(
                        f"Unexpected HTTP status: {status_code}"
                    )

                data = json.loads(raw_data.decode("utf-8"))

                if not data.get("success", False):
                    raise RuntimeError(
                        f"Delta API error: {data}"
                    )

                return data.get("result")

        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"HTTP Error {error.code}: {error.reason}"
            ) from error

        except urllib.error.URLError as error:
            raise RuntimeError(
                f"Connection Error: {error.reason}"
            ) from error

        except TimeoutError as error:
            raise RuntimeError(
                "API request timed out"
            ) from error

        except json.JSONDecodeError as error:
            raise RuntimeError(
                "Invalid JSON response from Delta Exchange"
            ) from error

    def get_product(self, symbol="BTCUSD"):
        """Fetch product specifications."""

        return self._get(
            f"/v2/products/{symbol}"
        )

    def get_orderbook(self, symbol="BTCUSD", depth=5):
        """Fetch Level 2 order book snapshot."""

        return self._get(
            f"/v2/l2orderbook/{symbol}?depth={depth}"
        )
