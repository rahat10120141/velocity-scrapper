#!/usr/bin/env python3
"""
VELOCITY SCALPER: 24/7 Standalone Cron & Background Execution Worker
Can be scheduled in cPanel Cron Jobs:
* * * * * cd /home/ragorytech/pythonapp && /home/ragorytech/virtualenv/pythonapp/3.11/bin/python cron_runner.py >> cron.log 2>&1

Or run manually via terminal/nohup:
nohup python3 cron_runner.py --daemon > cron.log 2>&1 &
"""
import os
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from engine import VelocityEngine

def main():
    daemon_mode = ("--daemon" in sys.argv)
    engine = VelocityEngine()
    
    if daemon_mode:
        print("[CRON RUNNER] Starting 24/7 background execution loop...", flush=True)
        engine.run_forever()
    else:
        print(f"[CRON RUNNER] Executing scheduled scan cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}...", flush=True)
        engine.scan_cycle()
        print("[CRON RUNNER] Scan cycle completed successfully.", flush=True)

if __name__ == "__main__":
    main()
