#!/usr/bin/env python3
"""
VELOCITY SCALPER: Standalone 24/7 Execution Daemon for cPanel
Can be executed from cPanel Terminal or managed via cPanel Cron Jobs.
"""
import os
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from engine import VelocityEngine

def main():
    print("=" * 65)
    print("⚡ VELOCITY SCALPER: 24/7 Scanning & Execution Daemon")
    print(f"📂 App Directory: {APP_DIR}")
    print("=" * 65)
    
    engine = VelocityEngine()
    try:
        engine.run_forever()
    except KeyboardInterrupt:
        print("\n[!] Received stop signal, shutting down daemon cleanly...")
        engine.is_running = False

if __name__ == "__main__":
    main()
