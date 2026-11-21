import unittest
from pathlib import Path

from scripts.notify_telegram import (
    HEADER,
    build_session_message,
    get_parquet_info,
    send_telegram_message,
)


class TestNotifyTelegram(unittest.TestCase):
    """Test suite for fail-safe Telegram notifier."""

    def test_build_session_message(self):
        msg = build_session_message(
            status="SUCCESS",
            duration_minutes=60,
            parquet_path="exports/delta_evening_20261122_1700_IST.parquet",
            rows=1500,
        )
        self.assertIn(HEADER, msg)
        self.assertIn("SUCCESS", msg)
        self.assertIn("60 min (1.0 hrs)", msg)
        self.assertIn("BTC, ETH, PAXG, XAUT", msg)
        self.assertIn("1,500", msg)

    def test_build_session_message_with_drive_status(self):
        msg = build_session_message(
            status="SUCCESS",
            duration="300 min",
            drive_status="Verified & Synced",
        )
        self.assertIn("300 min", msg)
        self.assertIn("Drive Sync:</b> ☁️ Verified & Synced", msg)

    def test_send_telegram_no_token_failsafe(self):
        # Should not raise exception, should return False gracefully
        result = send_telegram_message("Test message", token=None, chat_id=None)
        self.assertFalse(result)

    def test_get_parquet_info_nonexistent(self):
        info = get_parquet_info(Path("exports/non_existent.parquet"))
        self.assertFalse(info["exists"])
        self.assertEqual(info["filename"], "non_existent.parquet")


if __name__ == "__main__":
    unittest.main()
