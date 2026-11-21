import asyncio
import time
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from src.delta_ws import DeltaWebSocketClient, WebSocketFrame


class TestDeltaWebSocket(unittest.TestCase):
    """Test suite for stdlib RFC 6455 WebSocket client, framing, and fallback."""

    def test_frame_encoding_and_masking(self):
        payload = b"Hello, Delta!"
        encoded = WebSocketFrame.encode(WebSocketFrame.OP_TEXT, payload, mask=True)

        # Byte 0: 0x81 (FIN + TEXT)
        self.assertEqual(encoded[0], 0x81)
        # Byte 1: Mask bit (0x80) | len
        self.assertEqual(encoded[1], 0x80 | len(payload))
        # Total length: 2 (header) + 4 (mask) + len(payload)
        self.assertEqual(len(encoded), 2 + 4 + len(payload))

    def test_frame_encode_lengths(self):
        # Medium payload (126 to 65535)
        medium_payload = b"x" * 200
        encoded_med = WebSocketFrame.encode(WebSocketFrame.OP_TEXT, medium_payload, mask=False)
        self.assertEqual(encoded_med[1], 126)

        # Read back with StreamReader
        async def _test_read():
            reader = asyncio.StreamReader()
            reader.feed_data(encoded_med)
            opcode, data = await WebSocketFrame.read_frame(reader)
            self.assertEqual(opcode, WebSocketFrame.OP_TEXT)
            self.assertEqual(data, medium_payload)

        asyncio.run(_test_read())

    def test_ping_pong_frame(self):
        ping_payload = b"heartbeat"
        ping_frame = WebSocketFrame.encode(WebSocketFrame.OP_PING, ping_payload, mask=False)
        self.assertEqual(ping_frame[0], 0x89)

        async def _test_read_ping():
            reader = asyncio.StreamReader()
            reader.feed_data(ping_frame)
            opcode, data = await WebSocketFrame.read_frame(reader)
            self.assertEqual(opcode, WebSocketFrame.OP_PING)
            self.assertEqual(data, ping_payload)

        asyncio.run(_test_read_ping())

    def test_in_memory_book_snapshot_and_delta(self):
        mock_api = MagicMock()
        client = DeltaWebSocketClient(symbol="BTCUSD", rest_api=mock_api)

        snapshot = {
            "type": "snapshot",
            "buy": [
                {"price": "90000", "size": 10},
                {"price": "89990", "size": 25},
            ],
            "sell": [
                {"price": "90010", "size": 15},
                {"price": "90020", "size": 30},
            ],
        }
        client.apply_snapshot(snapshot)
        self.assertTrue(client.is_synced)
        self.assertEqual(len(client.bids), 2)
        self.assertEqual(len(client.asks), 2)

        # Apply incremental delta update:
        # update 90000 size to 5, delete 89990 (size 0), add 89995 (size 12)
        delta = {
            "type": "l2_updates",
            "buy": [
                {"price": "90000", "size": 5},
                {"price": "89990", "size": 0},
                {"price": "89995", "size": 12},
            ],
            "sell": [
                {"price": "90010", "size": 20},
            ],
        }
        client.apply_delta(delta)

        # 89990 must be deleted
        self.assertNotIn(Decimal(89990), client.bids)
        # 90000 updated to 5
        self.assertEqual(client.bids[Decimal(90000)], 5)
        # 89995 added with 12
        self.assertEqual(client.bids[Decimal(89995)], 12)
        # 90010 updated to 20
        self.assertEqual(client.asks[Decimal(90010)], 20)

        # Query orderbook
        book, source = client.get_orderbook(depth=5)
        self.assertEqual(source, "websocket")
        self.assertEqual(book["buy"][0]["price"], "90000")
        self.assertEqual(book["buy"][1]["price"], "89995")
        mock_api.get_orderbook.assert_not_called()

    def test_rest_fallback_when_stale(self):
        mock_api = MagicMock()
        mock_api.get_orderbook.return_value = {
            "buy": [{"price": "91000", "size": 10}],
            "sell": [{"price": "91000.5", "size": 10}],
        }
        client = DeltaWebSocketClient(symbol="BTCUSD", fallback_timeout=0.1, rest_api=mock_api)

        # Before sync: must fallback to REST
        book, source = client.get_orderbook()
        self.assertEqual(source, "rest_fallback")
        mock_api.get_orderbook.assert_called_once()

        # Now simulate a snapshot, making it fresh
        snapshot = {
            "buy": [{"price": "92000", "size": 10}],
            "sell": [{"price": "92001", "size": 10}],
        }
        client.apply_snapshot(snapshot)
        book, source = client.get_orderbook()
        self.assertEqual(source, "websocket")
        self.assertEqual(book["buy"][0]["price"], "92000")

        # Wait until it exceeds the 0.1s fallback timeout
        time.sleep(0.15)
        book, source = client.get_orderbook()
        self.assertEqual(source, "rest_fallback")


if __name__ == "__main__":
    unittest.main()
