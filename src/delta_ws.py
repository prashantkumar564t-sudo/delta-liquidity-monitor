"""
src/delta_ws.py
Standard-library-only RFC 6455 WebSocket client for Delta Exchange India L2 order book
with in-memory sorted Decimal book maintenance and automatic REST polling fallback.
"""

import asyncio
import base64
import hashlib
import json
import os
import ssl
import struct
import threading
import time
import urllib.parse
from decimal import Decimal

from src import config
from src.delta_api import DeltaAPI

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketFrame:
    """RFC 6455 frame serializer and deserializer."""

    OP_CONTINUATION = 0x0
    OP_TEXT = 0x1
    OP_BINARY = 0x2
    OP_CLOSE = 0x8
    OP_PING = 0x9
    OP_PONG = 0xA

    @staticmethod
    def encode(opcode: int, payload: bytes, mask: bool = True) -> bytes:
        """Encode a frame. Client-to-server frames MUST be masked."""
        length = len(payload)
        b0 = 0x80 | (opcode & 0x0F)  # FIN bit set

        if length <= 125:
            header = bytearray([b0, (0x80 if mask else 0) | length])
        elif length <= 65535:
            header = bytearray([b0, (0x80 if mask else 0) | 126])
            header.extend(struct.pack("!H", length))
        else:
            header = bytearray([b0, (0x80 if mask else 0) | 127])
            header.extend(struct.pack("!Q", length))

        if mask:
            mask_key = os.urandom(4)
            header.extend(mask_key)
            masked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            return bytes(header) + masked_payload
        return bytes(header) + payload

    @staticmethod
    async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
        """Read and decode one RFC 6455 frame from the stream."""
        head = await reader.readexactly(2)
        b0, b1 = head[0], head[1]

        opcode = b0 & 0x0F
        has_mask = bool(b1 & 0x80)
        length = b1 & 0x7F

        if length == 126:
            ext = await reader.readexactly(2)
            length = struct.unpack("!H", ext)[0]
        elif length == 127:
            ext = await reader.readexactly(8)
            length = struct.unpack("!Q", ext)[0]

        mask_key = await reader.readexactly(4) if has_mask else None
        data = await reader.readexactly(length)

        if has_mask:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
        else:
            payload = data

        return opcode, payload


class DeltaWebSocketClient:
    """
    Delta Exchange L2 WebSocket client using Python Standard Library only.
    Maintains an in-memory sorted Decimal order book and falls back to REST if stale (>3s).
    """

    def __init__(
        self,
        symbol: str = config.SYMBOL,
        ws_url: str = config.WS_URL,
        fallback_timeout: float = config.WS_TIMEOUT_SECONDS,
        rest_api: DeltaAPI | None = None,
    ):
        self.symbol = symbol
        self.ws_url = ws_url
        self.fallback_timeout = fallback_timeout
        self.rest_api = rest_api or DeltaAPI(timeout=config.API_TIMEOUT)

        self._lock = threading.Lock()
        self.bids: dict[Decimal, int] = {}
        self.asks: dict[Decimal, int] = {}

        self.last_tick_time: float = 0.0
        self.last_exchange_time: int | None = None
        self.is_connected: bool = False
        self.is_synced: bool = False
        self.running: bool = False

        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def apply_snapshot(self, payload: dict):
        """Replace internal order book with a full L2 snapshot."""
        bids_raw = payload.get("buy", [])
        asks_raw = payload.get("sell", [])

        new_bids = {}
        for item in bids_raw:
            price = Decimal(str(item["price"]))
            size = int(item["size"])
            if size > 0:
                new_bids[price] = size

        new_asks = {}
        for item in asks_raw:
            price = Decimal(str(item["price"]))
            size = int(item["size"])
            if size > 0:
                new_asks[price] = size

        with self._lock:
            self.bids = new_bids
            self.asks = new_asks
            self.last_tick_time = time.monotonic()
            self.last_exchange_time = payload.get("timestamp")
            self.is_synced = bool(self.bids and self.asks)

    def apply_delta(self, payload: dict):
        """Apply incremental L2 updates (size=0 deletes level, size>0 updates)."""
        bids_delta = payload.get("buy", [])
        asks_delta = payload.get("sell", [])

        with self._lock:
            for item in bids_delta:
                price = Decimal(str(item["price"]))
                size = int(item["size"])
                if size == 0:
                    self.bids.pop(price, None)
                else:
                    self.bids[price] = size

            for item in asks_delta:
                price = Decimal(str(item["price"]))
                size = int(item["size"])
                if size == 0:
                    self.asks.pop(price, None)
                else:
                    self.asks[price] = size

            self.last_tick_time = time.monotonic()
            if "timestamp" in payload:
                self.last_exchange_time = payload["timestamp"]
            self.is_synced = bool(self.bids and self.asks)

    def get_orderbook(self, depth: int = config.DEPTH) -> tuple[dict, str]:
        """
        Get latest L2 orderbook snapshot.
        Returns: (orderbook_dict, source_str: 'websocket' | 'rest_fallback')
        """
        now = time.monotonic()
        with self._lock:
            valid_ws = (
                self.is_synced
                and (now - self.last_tick_time <= self.fallback_timeout)
                and bool(self.bids)
                and bool(self.asks)
            )

            if valid_ws:
                sorted_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:depth]
                sorted_asks = sorted(self.asks.items(), key=lambda x: x[0])[:depth]

                return {
                    "symbol": self.symbol,
                    "buy": [{"price": str(p), "size": s} for p, s in sorted_bids],
                    "sell": [{"price": str(p), "size": s} for p, s in sorted_asks],
                }, "websocket"

        # Fallback to REST polling if WS is disconnected, stale (>3s), or un-synced
        book = self.rest_api.get_orderbook(symbol=self.symbol, depth=depth)
        return book, "rest_fallback"

    async def _handshake(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, path: str):
        """Perform RFC 6455 client opening handshake."""
        sec_key = base64.b64encode(os.urandom(16)).decode("ascii")
        expected_accept = base64.b64encode(
            hashlib.sha1((sec_key + WS_GUID).encode("ascii")).digest()
        ).decode("ascii")

        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {sec_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"User-Agent: Delta-Liquidity-Monitor/1.0\r\n"
            f"\r\n"
        )
        writer.write(req.encode("ascii"))
        await writer.drain()

        # Read HTTP response headers
        headers_data = await reader.readuntil(b"\r\n\r\n")
        headers_lines = headers_data.decode("latin1").split("\r\n")

        status_line = headers_lines[0]
        if "101" not in status_line:
            raise ConnectionError(f"WebSocket upgrade rejected: {status_line}")

        accept_header = None
        for line in headers_lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip().lower() == "sec-websocket-accept":
                    accept_header = v.strip()
                    break

        if accept_header != expected_accept:
            raise ConnectionError("Invalid Sec-WebSocket-Accept received from server")

    async def _subscribe(self, writer: asyncio.StreamWriter):
        """Send Delta Exchange L2 subscription request."""
        sub_msg = {
            "type": "subscribe",
            "payload": {
                "channels": [
                    {
                        "name": "l2_orderbook",
                        "symbols": [self.symbol]
                    }
                ]
            }
        }
        encoded = WebSocketFrame.encode(
            WebSocketFrame.OP_TEXT, json.dumps(sub_msg).encode("utf-8"), mask=True
        )
        writer.write(encoded)
        await writer.drain()

    async def run(self):
        """Main async connection and frame dispatch loop with reconnect logic."""
        parsed = urllib.parse.urlparse(self.ws_url)
        host = parsed.hostname or "socket.india.delta.exchange"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"

        ssl_ctx = ssl.create_default_context() if parsed.scheme == "wss" else None

        while self.running:
            try:
                reader, writer = await asyncio.open_connection(host, port, ssl=ssl_ctx)
                await self._handshake(reader, writer, host, path)
                await self._subscribe(writer)

                self.is_connected = True

                while self.running:
                    opcode, payload = await WebSocketFrame.read_frame(reader)

                    if opcode == WebSocketFrame.OP_PING:
                        # Respond with Pong
                        pong = WebSocketFrame.encode(
                            WebSocketFrame.OP_PONG, payload, mask=True
                        )
                        writer.write(pong)
                        await writer.drain()

                    elif opcode == WebSocketFrame.OP_CLOSE:
                        break

                    elif opcode == WebSocketFrame.OP_TEXT:
                        text = payload.decode("utf-8")
                        try:
                            msg = json.loads(text)
                            self._handle_message(msg)
                        except json.JSONDecodeError:
                            continue

            except (asyncio.CancelledError, KeyboardInterrupt):
                break
            except Exception:
                self.is_connected = False
                self.is_synced = False
                await asyncio.sleep(1.0)
            finally:
                self.is_connected = False
                self.is_synced = False

    def _handle_message(self, msg: dict):
        """Parse incoming Delta Exchange L2 orderbook messages."""
        msg_type = msg.get("type") or msg.get("action")
        channel = msg.get("channel")

        # Delta order book messages
        if msg_type in ("snapshot", "v2/l2orderbook") or (
            channel == "l2_orderbook" and "buy" in msg and "sell" in msg and msg.get("action") != "update"
        ):
            self.apply_snapshot(msg)
        elif msg_type in ("l2_updates", "update") or (
            channel == "l2_orderbook" and msg.get("action") == "update"
        ):
            self.apply_delta(msg)

    def start(self):
        """Start WebSocket worker in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            return

        self.running = True

        def _worker():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self.run())
            except (RuntimeError, asyncio.CancelledError):
                pass
            finally:
                try:
                    pending = asyncio.all_tasks(self._loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                self._loop.close()

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop background WebSocket worker."""
        self.running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
