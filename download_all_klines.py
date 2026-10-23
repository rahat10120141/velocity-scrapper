"""
Download full 2026 OHLCV data (1h and 15m) for all 5 pairs up to today (Oct 23, 2026).
Caches to data/klines/ for instant high-speed backtesting.
"""
import urllib.request
import json
import datetime
import time
import os
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]
INTERVALS = ["1h", "15m", "4h"]

os.makedirs("data/klines", exist_ok=True)

# Warmup from Dec 1, 2025 so indicators (200 EMA) are fully warmed up by Jan 1, 2026
warmup_dt = datetime.datetime(2025, 12, 1, 0, 0, tzinfo=datetime.timezone.utc)
end_dt = datetime.datetime(2026, 10, 23, 23, 59, tzinfo=datetime.timezone.utc)

warmup_ts = int(warmup_dt.timestamp() * 1000)
end_ts = int(end_dt.timestamp() * 1000)

headers = {"User-Agent": "Mozilla/5.0"}

def fetch_klines(symbol, interval):
    out_file = f"data/klines/{symbol}_{interval}_2026.csv"
    if os.path.exists(out_file) and os.path.getsize(out_file) > 10000:
        print(f"  {symbol} {interval} already cached: {out_file}")
        return pd.read_csv(out_file, index_col=0, parse_dates=True)
    
    print(f"Fetching {symbol} {interval} from Binance Futures...")
    collected = []
    cur_start = warmup_ts
    
    step_ms = {"15m": 15 * 60 * 1000, "1h": 3600 * 1000, "4h": 4 * 3600 * 1000}[interval]
    
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
            print(f"    Error fetching {cur_start}: {e}, retrying...")
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
    print(f"  Saved {symbol} {interval}: {len(df):,} bars ({df.index[0]} to {df.index[-1]})")
    return df

for sym in SYMBOLS:
    for inv in ["1h", "15m", "4h"]:
        fetch_klines(sym, inv)

print("\nAll historical klines cached successfully.")
