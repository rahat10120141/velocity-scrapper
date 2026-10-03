"""
VELOCITY SCALPER: Real Tick Portfolio Backtester
Target Store: /home/rahat/Documents/claude/tick_data
Replays authentic sub-second Binance aggTrades across 6 major crypto assets:
BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, DOGEUSDT, LINKUSDT
Models:
  - 10x leverage, $100 starting balance
  - 1.0 ATR Stop Loss, 2.2R Take Profit
  - +1.0R Break-Even Lock (+0.18% fee offset)
  - 0.04% Taker fee on entry and exit (0.08% roundtrip)
  - Daily Circuit Breakers ($3.00 profit lock, -$3.00 max loss defense)
  - Max 1 open position across entire portfolio
"""
import os
import zipfile
import io
import csv
import json
import time
import datetime
import urllib.request
import pandas as pd
import numpy as np

TICK_STORE = "/home/rahat/Documents/claude/tick_data"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT"]

def get_available_tick_files():
    if not os.path.exists(TICK_STORE):
        return {}
    files = os.listdir(TICK_STORE)
    store = {}
    for s in SYMBOLS:
        store[s] = []
        for f in files:
            if f.startswith(f"{s}-aggTrades-") and f.endswith(".zip"):
                month = f.replace(f"{s}-aggTrades-", "").replace(".zip", "")
                store[s].append(month)
        store[s].sort()
    return store

def fetch_1h_klines(symbol, start_dt, end_dt):
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    collected = []
    cur_start = start_ts
    headers = {"User-Agent": "Mozilla/5.0"}
    
    while cur_start < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&startTime={cur_start}&endTime={end_ts}&limit=1000"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            break
        collected.extend(data)
        cur_start = data[-1][0] + (3600 * 1000)
        if len(data) < 1000:
            break
        time.sleep(0.03)

    df = pd.DataFrame(collected, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "count", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore"
    ])
    df.drop_duplicates(subset=["open_time"], inplace=True)
    df.sort_values("open_time", inplace=True)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df.set_index("time", inplace=True)
    return df

def prepare_signals(df):
    c = df["close"]
    h = df["high"]
    l = df["low"]
    
    df["ema_fast"] = c.ewm(span=9, adjust=False).mean()
    df["ema_slow"] = c.ewm(span=21, adjust=False).mean()
    df["ema_trend"] = c.ewm(span=200, adjust=False).mean()
    
    c_prev = c.shift(1)
    tr = np.maximum(h - l, np.maximum(abs(h - c_prev), abs(l - c_prev)))
    df["atr"] = tr.rolling(14).mean()
    
    df["regime"] = 0
    df.loc[c > df["ema_trend"], "regime"] = 1
    df.loc[c < df["ema_trend"], "regime"] = -1
    
    fast = df["ema_fast"]
    slow = df["ema_slow"]
    buy_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    sell_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    
    df["signal"] = 0
    df.loc[(df["regime"] == 1) & buy_cross, "signal"] = 1
    df.loc[(df["regime"] == -1) & sell_cross, "signal"] = -1
    return df

def stream_ticks(symbol, month):
    zip_path = os.path.join(TICK_STORE, f"{symbol}-aggTrades-{month}.zip")
    if not os.path.exists(zip_path):
        return
    with zipfile.ZipFile(zip_path, 'r') as z:
        csv_name = z.namelist()[0]
        with z.open(csv_name) as f:
            wrapper = io.TextIOWrapper(f, encoding='utf-8')
            reader = csv.reader(wrapper)
            first_row = next(reader, None)
            if first_row and not first_row[0].isdigit():
                pass # header
            elif first_row:
                yield int(first_row[5]), float(first_row[1])
            for row in reader:
                if len(row) >= 6:
                    yield int(row[5]), float(row[1])

def run_single_pair_tick_audit(symbol="BTCUSDT", month="2026-09", initial_balance=100.0):
    print(f"\n==========================================================================")
    print(f"  REAL TICK AUDIT: {symbol} | Month: {month} | Store: {TICK_STORE}")
    print(f"==========================================================================")
    
    zip_path = os.path.join(TICK_STORE, f"{symbol}-aggTrades-{month}.zip")
    if not os.path.exists(zip_path):
        print(f"Error: {zip_path} not found!")
        return None
        
    year, mon = map(int, month.split("-"))
    # Warmup 10 days before month start
    start_dt = datetime.datetime(year, mon, 1, 0, 0)
    warmup_dt = start_dt - datetime.timedelta(days=15)
    if mon == 12:
        end_dt = datetime.datetime(year + 1, 1, 1, 0, 0)
    else:
        end_dt = datetime.datetime(year, mon + 1, 1, 0, 0)
        
    print(f"Fetching 1h macro indicators from {warmup_dt.date()} to {end_dt.date()}...")
    df = fetch_1h_klines(symbol, warmup_dt, end_dt)
    df = prepare_signals(df)
    
    # Filter bars strictly within the target month
    month_df = df.loc[start_dt:end_dt].copy()
    signals_count = (month_df["signal"] != 0).sum()
    print(f"Loaded {len(month_df)} 1H bars with {signals_count} potential trigger signals.")
    
    # Map each hour's signal parameters
    hourly_signals = {}
    for t, row in month_df.iterrows():
        ts_ms = int(t.timestamp() * 1000)
        if row["signal"] != 0 and not np.isnan(row["atr"]) and row["atr"] > 0:
            hourly_signals[ts_ms] = {
                "time": t,
                "direction": int(row["signal"]),
                "atr": row["atr"],
                "close": row["close"]
            }
            
    print(f"Replaying sub-second ticks from {zip_path}...")
    
    balance = initial_balance
    peak_balance = initial_balance
    max_dd = 0.0
    
    active_trade = None
    trades = []
    daily_pnl = {}
    tick_count = 0
    start_perf = time.time()
    
    for ts_ms, price in stream_ticks(symbol, month):
        tick_count += 1
        
        # Fast Integer Day Bucket (86400000 ms per day)
        day_bucket = ts_ms // 86400000
        if day_bucket not in daily_pnl:
            daily_pnl[day_bucket] = 0.0
            
        # Circuit Breaker Check ($3.00 profit lock, -$3.00 daily loss)
        day_pnl = daily_pnl[day_bucket]
        circuit_active = (day_pnl >= 3.00) or (day_pnl <= -3.00)
        
        # 1. Manage Active Trade
        if active_trade is not None:
            direction = active_trade["direction"]
            entry_p = active_trade["entry_price"]
            sl_p = active_trade["sl_price"]
            tp_p = active_trade["tp_price"]
            be_trig = active_trade["be_trigger"]
            pos_size = active_trade["pos_size"]
            closed = False
            exit_price = price
            reason = ""
            
            if direction == 1: # LONG
                # Break-Even trigger
                if not active_trade["be_locked"] and price >= be_trig:
                    active_trade["sl_price"] = entry_p * 1.0018
                    active_trade["be_locked"] = True
                # Take Profit hit
                if price >= tp_p:
                    closed = True
                    exit_price = tp_p
                    reason = "TP_HIT"
                # Stop Loss hit
                elif price <= active_trade["sl_price"]:
                    closed = True
                    exit_price = active_trade["sl_price"]
                    reason = "BE_EXIT" if active_trade["be_locked"] else "SL_HIT"
                    
            elif direction == -1: # SHORT
                # Break-Even trigger
                if not active_trade["be_locked"] and price <= be_trig:
                    active_trade["sl_price"] = entry_p * (1 - 0.0018)
                    active_trade["be_locked"] = True
                # Take Profit hit
                if price <= tp_p:
                    closed = True
                    exit_price = tp_p
                    reason = "TP_HIT"
                # Stop Loss hit
                elif price >= active_trade["sl_price"]:
                    closed = True
                    exit_price = active_trade["sl_price"]
                    reason = "BE_EXIT" if active_trade["be_locked"] else "SL_HIT"
                    
            if closed:
                gross_pnl = (exit_price - entry_p) * pos_size if direction == 1 else (entry_p - exit_price) * pos_size
                entry_fee = (pos_size * entry_p) * 0.0004
                exit_fee = (pos_size * exit_price) * 0.0004
                total_fees = entry_fee + exit_fee
                net_pnl = gross_pnl - total_fees
                
                balance += net_pnl
                daily_pnl[day_bucket] += net_pnl
                if balance > peak_balance:
                    peak_balance = balance
                dd = peak_balance - balance
                if dd > max_dd:
                    max_dd = dd
                    
                trades.append({
                    "symbol": symbol,
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "entry_time": active_trade["entry_time"],
                    "exit_time": datetime.datetime.fromtimestamp(ts_ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "entry_price": entry_p,
                    "exit_price": exit_price,
                    "reason": reason,
                    "net_pnl": net_pnl,
                    "fees": total_fees,
                    "balance": balance
                })
                active_trade = None
                
        # 2. Check for New Signal Entry
        if active_trade is None and not circuit_active:
            # Check if this tick falls at the start of a signal hour
            hour_bucket = (ts_ms // (3600 * 1000)) * (3600 * 1000)
            if hour_bucket in hourly_signals:
                sig_info = hourly_signals.pop(hour_bucket) # Consume signal
                direction = sig_info["direction"]
                atr = sig_info["atr"]
                entry_p = price
                
                risk_usd = 2.50
                sl_dist = 1.0 * atr
                tp_dist = 2.2 * sl_dist
                pos_size = risk_usd / sl_dist
                
                # Check maximum allowed margin ($25 at 10x = $250 notional)
                max_pos_size = 250.0 / entry_p
                pos_size = min(pos_size, max_pos_size)
                
                if direction == 1:
                    sl_price = entry_p - sl_dist
                    tp_price = entry_p + tp_dist
                    be_trigger = entry_p + sl_dist # +1.0R
                else:
                    sl_price = entry_p + sl_dist
                    tp_price = entry_p - tp_dist
                    be_trigger = entry_p - sl_dist # +1.0R
                    
                active_trade = {
                    "direction": direction,
                    "entry_price": entry_p,
                    "sl_price": sl_price,
                    "tp_price": tp_price,
                    "be_trigger": be_trigger,
                    "be_locked": False,
                    "pos_size": pos_size,
                    "entry_time": datetime.datetime.fromtimestamp(ts_ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                }

    elapsed = time.time() - start_perf
    print(f"Replayed {tick_count:,} sub-second ticks in {elapsed:.1f}s ({tick_count / max(elapsed, 0.001):,.0f} ticks/s).")
    
    # Analyze results
    n_trades = len(trades)
    if n_trades == 0:
        print("No trades triggered.")
        return None
        
    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    win_rate = (len(wins) / n_trades) * 100
    
    total_net = sum(t["net_pnl"] for t in trades)
    total_fees = sum(t["fees"] for t in trades)
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else 999.0
    
    target_hit_days = sum(1 for p in daily_pnl.values() if p >= 3.00)
    loss_hit_days = sum(1 for p in daily_pnl.values() if p <= -3.00)
    active_days = sum(1 for p in daily_pnl.values() if p != 0)
    
    print(f"\n--------------------------------------------------------------------------")
    print(f"  RESULTS FOR {symbol} ({month})")
    print(f"--------------------------------------------------------------------------")
    print(f"  Total Trades:         {n_trades} ({n_trades / max(1, active_days):.1f} trades/day)")
    print(f"  Win Rate:             {win_rate:.1f}% ({len(wins)} W / {len(losses)} L)")
    print(f"  Starting Balance:     ${initial_balance:.2f}")
    print(f"  Ending Balance:       ${balance:.2f} ({((balance - initial_balance)/initial_balance)*100:+.1f}%)")
    print(f"  Net Realized Profit:  ${total_net:+.2f}")
    print(f"  Exchange Fees Paid:   ${total_fees:.2f}")
    print(f"  Profit Factor (PF):   {pf:.2f}")
    print(f"  Maximum Drawdown:     ${max_dd:.2f} ({(max_dd/initial_balance)*100:.1f}%)")
    print(f"  Daily Target ($3) Hit:{target_hit_days} days")
    print(f"  Daily Max Loss Hit:   {loss_hit_days} days")
    print(f"--------------------------------------------------------------------------\n")
    
    return {
        "symbol": symbol,
        "month": month,
        "trades": n_trades,
        "win_rate": win_rate,
        "net_pnl": total_net,
        "fees": total_fees,
        "pf": pf,
        "max_dd": max_dd,
        "final_balance": balance,
        "target_days": target_hit_days,
        "loss_days": loss_hit_days
    }

if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    m = sys.argv[2] if len(sys.argv) > 2 else "2026-09"
    run_single_pair_tick_audit(sym, m)
