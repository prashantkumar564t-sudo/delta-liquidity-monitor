"""
launcher.py
Launches the collector process and the RAM/Resource monitor concurrently.
"""

import subprocess
import sys
import time
from pathlib import Path

def main():
    python_exe = sys.executable
    root_dir = Path(__file__).resolve().parent

    main_script = root_dir / "src" / "main.py"
    monitor_script = root_dir / "monitor" / "ram_monitor.py"

    print("=" * 60)
    print("Launching Delta Liquidity Monitor & Profiler")
    print("=" * 60)

    # 1. Start Main Collector
    collector_proc = subprocess.Popen([python_exe, str(main_script)])
    print(f"[Launcher] Collector started (PID: {collector_proc.pid})")

    # 2. Start Resource Monitor with collector's PID
    monitor_proc = subprocess.Popen([python_exe, str(monitor_script), str(collector_proc.pid)])
    print(f"[Launcher] Monitor started (PID: {monitor_proc.pid})")

    try:
        # Wait for collector to complete
        collector_proc.wait()
    except KeyboardInterrupt:
        print("\n[Launcher] Shutting down...")
        collector_proc.terminate()
    finally:
        # Stop monitor process
        if monitor_proc.poll() is None:
            time.sleep(1)
            monitor_proc.terminate()

    print("[Launcher] All tasks finished successfully.")

if __name__ == "__main__":
    main()