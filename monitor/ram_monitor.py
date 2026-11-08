"""
monitor/ram_monitor.py
Tracks RAM of target process using Standard Library only (Windows-safe).
"""

import sys
import time
import os
import csv
from datetime import datetime, timezone
from pathlib import Path


def is_process_running(pid):
    """Check if process is alive without sending signals (Windows-safe)."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        exit_code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return exit_code.value == 259  # 259 = STILL_ACTIVE
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def get_process_memory_mb(pid):
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ('cb', wintypes.DWORD),
                    ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t),
                    ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t),
                ]

            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_VM_READ = 0x0010
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
            )
            if not handle:
                return 0.0

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            )
            ctypes.windll.kernel32.CloseHandle(handle)
            return counters.WorkingSetSize / (1024 * 1024)
        else:
            with open(f"/proc/{pid}/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return float(line.split()[1]) / 1024.0
    except Exception:
        return 0.0
    return 0.0


def monitor(target_pid, interval=1.0):
    project_root = Path(__file__).resolve().parent.parent
    log_file = project_root / "logs" / "system_resources.csv"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_exists = log_file.exists() and log_file.stat().st_size > 0

    try:
        with log_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp_utc", "target_pid", "memory_mb", "peak_memory_mb"])

            peak_memory = 0.0
            while True:
                # सुरक्षित विंडोज़ प्रोसेस चेक
                if not is_process_running(target_pid):
                    break

                mem = get_process_memory_mb(target_pid)
                if mem > peak_memory:
                    peak_memory = mem

                writer.writerow([
                    datetime.now(timezone.utc).isoformat(),
                    target_pid,
                    f"{mem:.2f}",
                    f"{peak_memory:.2f}"
                ])
                f.flush()
                time.sleep(interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    if len(sys.argv) > 1:
        pid = int(sys.argv[1])
        monitor(pid)