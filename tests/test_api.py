import io
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from src.delta_api import DeltaAPI


class TestDeltaAPI(unittest.TestCase):
    """Test suite for Delta Exchange REST client with mocked HTTP."""

    def setUp(self):
        self.api = DeltaAPI(timeout=5)

    @patch("urllib.request.urlopen")
    def test_get_product_success(self, mock_urlopen):
        fake_response = {
            "success": True,
            "result": {
                "symbol": "BTCUSD",
                "id": 1,
                "contract_value": "0.001"
            }
        }
        mock_cm = MagicMock()
        mock_cm.status = 200
        mock_cm.read.return_value = json.dumps(fake_response).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        result = self.api.get_product("BTCUSD")
        self.assertEqual(result["symbol"], "BTCUSD")
        self.assertEqual(result["contract_value"], "0.001")

    @patch("urllib.request.urlopen")
    def test_get_orderbook_success(self, mock_urlopen):
        fake_response = {
            "success": True,
            "result": {
                "symbol": "BTCUSD",
                "buy": [{"price": "90000", "size": 10}],
                "sell": [{"price": "90000.5", "size": 10}]
            }
        }
        mock_cm = MagicMock()
        mock_cm.status = 200
        mock_cm.read.return_value = json.dumps(fake_response).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        result = self.api.get_orderbook("BTCUSD", depth=5)
        self.assertIn("buy", result)
        self.assertIn("sell", result)
        self.assertEqual(result["buy"][0]["price"], "90000")

    @patch("urllib.request.urlopen")
    def test_api_failure_response(self, mock_urlopen):
        fake_response = {
            "success": False,
            "error": "Symbol not found"
        }
        mock_cm = MagicMock()
        mock_cm.status = 200
        mock_cm.read.return_value = json.dumps(fake_response).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        with self.assertRaises(RuntimeError):
            self.api.get_product("INVALID")

    @patch("urllib.request.urlopen")
    def test_http_error_handling(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://dummy", code=429, msg="Too Many Requests", hdrs={}, fp=io.BytesIO()
        )
        with self.assertRaises(RuntimeError) as ctx:
            self.api.get_product("BTCUSD")
        self.assertIn("429", str(ctx.exception))
        self.assertGreaterEqual(self.api.last_rtt_ns, 0)

    @patch("urllib.request.urlopen")
    def test_rtt_latency_tracking(self, mock_urlopen):
        fake_response = {"success": True, "result": {"symbol": "BTCUSD"}}
        mock_cm = MagicMock()
        mock_cm.status = 200
        mock_cm.read.return_value = json.dumps(fake_response).encode("utf-8")
        mock_cm.__enter__.return_value = mock_cm
        mock_urlopen.return_value = mock_cm

        self.api.get_product("BTCUSD")
        self.assertGreaterEqual(self.api.last_rtt_ns, 0)
        self.assertGreaterEqual(self.api.last_rtt_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
