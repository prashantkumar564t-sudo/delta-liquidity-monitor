"""
scripts/notify_telegram.py
Fail-safe Telegram notifier for Delta Options Microstructure cloud runs.
Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment variables.
Uses strictly Python Standard Library (urllib.request, json).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
HEADER = "📊 [DELTA OPTIONS MICROSTRUCTURE]"


def get_parquet_info(parquet_path: str | Path) -> dict:
    """Inspect parquet file for row count and file size."""
    p = Path(parquet_path)
    if not p.exists():
        return {"exists": False, "filename": p.name}

    file_size_bytes = p.stat().st_size
    file_size_kb = file_size_bytes / 1024.0
    file_size_mb = file_size_kb / 1024.0
    size_str = f"{file_size_mb:.2f} MB" if file_size_mb >= 1.0 else f"{file_size_kb:.2f} KB"

    row_count = None
    try:
        import duckdb
        con = duckdb.connect()
        p_str = str(p.resolve()).replace("\\", "/")
        res = con.execute(f"SELECT count(*) FROM '{p_str}'").fetchone()
        row_count = res[0] if res else None
        con.close()
    except Exception:
        pass

    return {
        "exists": True,
        "filename": p.name,
        "size_str": size_str,
        "file_size_bytes": file_size_bytes,
        "row_count": row_count,
    }


def send_telegram_message(
    text: str,
    token: str | None = None,
    chat_id: str | None = None,
    timeout: int = 15,
) -> bool:
    """Send formatted alert to Telegram bot channel/chat."""
    token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[!] Telegram notifications disabled: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                print("[+] Telegram alert dispatched successfully.")
                return True
            print(f"[!] Telegram API returned status: {resp.status}")
            return False
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore")
        print(f"[!] Telegram HTTPError {err.code}: {body}")
        return False
    except Exception as err:
        print(f"[!] Telegram notification error: {err}")
        return False


def build_session_message(
    status: str = "SUCCESS",
    duration_minutes: int | None = None,
    duration: str | None = None,
    parquet_path: str | None = None,
    rows: int | None = None,
    drive_status: str | None = None,
    message: str | None = None,
) -> str:
    """Build standardized HTML notification message."""
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    status_emoji = "✅" if status.upper() in ("SUCCESS", "COMPLETED") else "⚠️"

    lines = [
        f"<b>{HEADER}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"<b>Status:</b> {status_emoji} {status.upper()}",
        f"<b>Timestamp:</b> <code>{now_ist}</code>",
    ]

    dur_str = None
    if duration:
        dur_str = duration
    elif duration_minutes is not None:
        hours = duration_minutes / 60.0
        dur_str = f"{duration_minutes} min ({hours:.1f} hrs)" if hours >= 1.0 else f"{duration_minutes} min"

    if dur_str:
        lines.append(f"<b>Duration:</b> {dur_str}")

    if parquet_path:
        p_info = get_parquet_info(parquet_path)
        if p_info["exists"]:
            p_rows = rows if rows is not None else p_info.get("row_count")
            lines.append(f"<b>Parquet:</b> <code>{p_info['filename']}</code>")
            if p_rows is not None:
                lines.append(f"<b>Rows Logged:</b> <code>{p_rows:,}</code>")
            lines.append(f"<b>File Size:</b> {p_info['size_str']} (ZSTD)")
        else:
            lines.append(f"<b>Parquet:</b> <code>{p_info['filename']}</code>")
            if rows is not None:
                lines.append(f"<b>Rows Logged:</b> <code>{rows:,}</code>")
    elif rows is not None:
        lines.append(f"<b>Rows Logged:</b> <code>{rows:,}</code>")

    lines.append("<b>Underlyings:</b> BTC, ETH, PAXG, XAUT")
    lines.append("<b>Scope:</b> 0-DTE & 1-DTE OTM Options + L2 Book")

    if drive_status:
        drive_emoji = "☁️" if "Verified" in drive_status or "Synced" in drive_status else "⚠️"
        lines.append(f"<b>Drive Sync:</b> {drive_emoji} {drive_status}")

    if message:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"<i>{message}</i>")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(description="Telegram Notification Dispatcher")
    parser.add_argument("--message", default=None, help="Custom message body")
    parser.add_argument("--status", default="SUCCESS", help="Run status: SUCCESS or FAILED")
    parser.add_argument("--duration", default=None, help="Run duration string (e.g. '300 min')")
    parser.add_argument("--duration-minutes", type=int, default=None, help="Run duration in minutes")
    parser.add_argument(
        "--parquet", "--parquet-file", dest="parquet", default=None, help="Path to exported Parquet file"
    )
    parser.add_argument("--rows", type=int, default=None, help="Total rows captured")
    parser.add_argument("--drive-status", default=None, help="Google Drive upload status")
    return parser.parse_args()


def main():
    args = parse_args()
    msg = build_session_message(
        status=args.status,
        duration_minutes=args.duration_minutes,
        duration=args.duration,
        parquet_path=args.parquet,
        rows=args.rows,
        drive_status=args.drive_status,
        message=args.message,
    )
    print("\n" + msg + "\n")
    # Fail-safe execution: never exit with non-zero code even on failure
    send_telegram_message(text=msg)
    sys.exit(0)


if __name__ == "__main__":
    main()
