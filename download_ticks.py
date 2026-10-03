"""
Tick Data Downloader for Claude Workspace
Target: /home/rahat/Documents/claude/tick_data
Downloads Binance Official Monthly aggTrades (Futures UM) for the last 6 months (2026-04 to 2026-09)
Pairs: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, DOGEUSDT, LINKUSDT
"""
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

TARGET_DIR = "/home/rahat/Documents/claude/tick_data"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT"]
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/aggTrades"

os.makedirs(TARGET_DIR, exist_ok=True)

def download_file(symbol, month):
    filename = f"{symbol}-aggTrades-{month}.zip"
    filepath = os.path.join(TARGET_DIR, filename)
    url = f"{BASE_URL}/{symbol}/{filename}"
    
    # Check remote size
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as resp:
            remote_size = int(resp.headers.get("Content-Length", 0))
    except Exception as e:
        return f"[{symbol} {month}] Failed to get remote size: {e}"
        
    # Check if local file already exists and matches size
    if os.path.exists(filepath):
        local_size = os.path.getsize(filepath)
        if local_size == remote_size and remote_size > 0:
            return f"[{symbol} {month}] ALREADY COMPLETE ({local_size / (1024*1024):.1f} MB), skipping."
        elif local_size > 0:
            print(f"[{symbol} {month}] Partial file found ({local_size} vs {remote_size}), re-downloading...")
            
    temp_path = filepath + ".tmp"
    start_t = time.time()
    downloaded = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as response, open(temp_path, "wb") as out_file:
            chunk_size = 1024 * 1024 # 1MB
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                
        # Rename after complete
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(temp_path, filepath)
        elapsed = time.time() - start_t
        speed = (downloaded / (1024*1024)) / max(elapsed, 0.001)
        return f"[{symbol} {month}] SUCCESS: {downloaded / (1024*1024):.1f} MB in {elapsed:.1f}s ({speed:.2f} MB/s)"
    except Exception as e:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass
        return f"[{symbol} {month}] FAILED: {e}"

if __name__ == "__main__":
    tasks = []
    for s in SYMBOLS:
        for m in MONTHS:
            tasks.append((s, m))
            
    print(f"Starting download of {len(tasks)} tick archives to {TARGET_DIR}...")
    print(f"Workers: 4 parallel downloads")
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(download_file, s, m): (s, m) for s, m in tasks}
        for future in as_completed(futures):
            res = future.result()
            print(res, flush=True)
            
    print("\nALL TICK DOWNLOAD TASKS FINISHED!")
