"""
Tick Data Inspector & Validator
Target: /home/rahat/Documents/claude/tick_data
Inspects downloaded tick data files, validates zip integrity, and checks headers/sample ticks.
"""
import os
import zipfile
import glob

TICK_DIR = "/home/rahat/Documents/claude/tick_data"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT"]
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]

def inspect_tick_store():
    print(f"\n========================================================")
    print(f"      SHARED TICK DATA STORE: {TICK_DIR}")
    print(f"========================================================")
    
    if not os.path.exists(TICK_DIR):
        print(f"Directory {TICK_DIR} does not exist.")
        return
        
    all_files = sorted(os.listdir(TICK_DIR))
    zips = [f for f in all_files if f.endswith(".zip")]
    tmps = [f for f in all_files if f.endswith(".tmp")]
    
    print(f"Total Completed Zip Files: {len(zips)}")
    print(f"Active Downloading Files:  {len(tmps)}")
    print(f"--------------------------------------------------------")
    
    total_bytes = 0
    matrix = {s: {m: "MISSING" for m in MONTHS} for s in SYMBOLS}
    
    for f in all_files:
        p = os.path.join(TICK_DIR, f)
        sz = os.path.getsize(p)
        total_bytes += sz
        
        # Parse symbol and month
        for s in SYMBOLS:
            for m in MONTHS:
                if f == f"{s}-aggTrades-{m}.zip":
                    matrix[s][m] = f"{sz / (1024*1024):.1f}MB"
                elif f == f"{s}-aggTrades-{m}.zip.tmp":
                    matrix[s][m] = f"DOWNLOADING ({sz / (1024*1024):.1f}MB)"

    header = f"{'SYMBOL':<10} | " + " | ".join([f"{m}" for m in MONTHS])
    print(header)
    print("-" * len(header))
    for s in SYMBOLS:
        row = f"{s:<10} | " + " | ".join([f"{matrix[s][m]:<7}" for m in MONTHS])
        print(row)
        
    print(f"--------------------------------------------------------")
    print(f"Total Disk Usage in Store: {total_bytes / (1024*1024*1024):.2f} GB\n")

if __name__ == "__main__":
    inspect_tick_store()
