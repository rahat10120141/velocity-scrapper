"""
Download full 2025 1H and 15M candlestick data for BTC, ETH, SOL, BNB, LINK from Binance Futures.
Caches to data/klines/ for comprehensive 2025-2026 multi-year backtesting.
"""
import urllib.request
import json
import datetime
import time
import os
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]
os.makedirs("data/klines", exist_ok=True)

# 2025: Dec 15, 2024 to Dec 31, 2025
start_dt = datetime.datetime(2024, 12, 15, 0, 0, tzinfo=datetime.timezone.utc)
end_dt = datetime.datetime(2025, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)

start_ts = int(start_dt.timestamp() * 1000)
end_ts = int(end_dt.timestamp() * 1000)
headers = {"User-Agent": "Mozilla/5.0"}

def fetch_2025(symbol, interval="1h"):
    out_file = f"data/klines/{symbol}_{interval}_2025.csv"
    if os.path.exists(out_file) and os.path.getsize(out_file) > 10000:
        print(f"  {symbol} {interval} 2025 already cached.")
        return
        
    print(f"Fetching {symbol} {interval} for 2025...")
    collected = []
    cur_start = start_ts
    step_ms = {"15m": 15 * 60 * 1000, "1h": 3600 * 1000}[interval]
    
    while cur_start < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={cur_start}&endTime={end_ts}&limit=1000"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            if not data:
                break
            collected.extend(data)
            cur_start = data[-1][0] + step_ms
            if len(data) < 1000:
                break
            time.sleep(0.04)
        except Exception as e:
            print(f"    Error {cur_start}: {e}, retrying...")
            time.sleep(1)
            
    df = pd.DataFrame(collected, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "count", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore"
    ])
    df.drop_duplicates(subset=["open_time"], inplace=True)
    df.sort_values("open_time", inplace=True)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = df[col].astype(float)
    df.set_index("time", inplace=True)
    df.to_csv(out_file)
    print(f"  Saved {symbol} {interval} 2025: {len(df):,} bars.")

for sym in SYMBOLS:
    fetch_2025(sym, "1h")

print("All 2025 1H data successfully cached!")
