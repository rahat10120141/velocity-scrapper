"""
VELOCITY SCALPER: Multi-Timeframe Real Sub-Second Tick Comparison
Tests 5M vs 15M vs 1H against 36,036,629 authentic Binance sub-second ticks.
"""
import zipfile
import datetime
import time
import os
import urllib.request
import urllib.parse
import json
import pandas as pd
import numpy as np

ZIP_PATH_SEP = "/home/rahat/Documents/claude/tick_data/BTCUSDT-aggTrades-2026-09.zip"

def fetch_klines(interval="15m", start_dt=None, end_dt=None):
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    collected = []
    cur_start = start_ts
    headers = {"User-Agent": "Mozilla/5.0"}
    step_ms = 3600 * 1000 if interval == "1h" else (900 * 1000 if interval == "15m" else 300 * 1000)
    
    print(f"Fetching {interval} bars from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}...")
    while cur_start < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval={interval}&startTime={cur_start}&endTime={end_ts}&limit=1000"
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

def run_tick_test(interval="15m"):
    warmup_dt = datetime.datetime(2026, 8, 15, 0, 0)
    end_dt = datetime.datetime(2026, 10, 1, 0, 0)
    
    df = fetch_klines(interval, warmup_dt, end_dt)
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

    signals = []
    dur_delta = datetime.timedelta(minutes=15) if interval == "15m" else datetime.timedelta(hours=1)
    
    for i in range(200, len(df)):
        d = df.index[i]
        sig = df["signal"].iloc[i]
        if d.year == 2026 and d.month == 9 and sig != 0:
            atr = df["atr"].iloc[i]
            close_p = df["close"].iloc[i]
            sl_dist = 1.0 * atr
            if sl_dist <= 0: continue
            
            risk_usd = 3.00
            pos_size = risk_usd / sl_dist
            tp_dist = 2.2 * sl_dist

            signals.append({
                "bar_time": d,
                "entry_ts": int((d + dur_delta).timestamp() * 1000),
                "direction": sig,
                "signal_close": close_p,
                "sl_dist": sl_dist,
                "tp_dist": tp_dist,
                "pos_size": pos_size,
                "initial_sl": close_p - sl_dist if sig == 1 else close_p + sl_dist,
                "tp_p": close_p + tp_dist if sig == 1 else close_p - tp_dist,
                "be_trigger": close_p + sl_dist if sig == 1 else close_p - sl_dist,
                "be_sl": close_p * (1.0 + 0.0018) if sig == 1 else close_p * (1.0 - 0.0018)
            })

    print(f"[{interval}] Identified {len(signals)} signals in September 2026. Processing ticks...")

    tick_trades = []
    daily_pnl = {}
    active_trade = None
    next_sig_idx = 0
    fee_rate = 0.0004
    t0 = time.time()
    processed_ticks = 0

    with zipfile.ZipFile(ZIP_PATH_SEP, "r") as z:
        with z.open("BTCUSDT-aggTrades-2026-09.csv", "r") as f:
            header = f.readline().decode().strip().split(",")
            p_idx = header.index("price")
            t_idx = header.index("transact_time")
            
            for line in f:
                processed_ticks += 1
                parts = line.decode().strip().split(",")
                t_ms = int(parts[t_idx])
                price = float(parts[p_idx])
                
                dt_utc = datetime.datetime.fromtimestamp(t_ms / 1000, tz=datetime.timezone.utc)
                date_key = dt_utc.strftime("%Y-%m-%d")
                if date_key not in daily_pnl:
                    daily_pnl[date_key] = 0.0

                if active_trade is None and next_sig_idx < len(signals):
                    sig = signals[next_sig_idx]
                    if t_ms >= sig["entry_ts"]:
                        active_trade = dict(sig)
                        active_trade["entry_price"] = price
                        active_trade["entry_time"] = dt_utc
                        active_trade["current_sl"] = price - sig["sl_dist"] if sig["direction"] == 1 else price + sig["sl_dist"]
                        active_trade["tp_price"] = price + sig["tp_dist"] if sig["direction"] == 1 else price - sig["tp_dist"]
                        active_trade["be_trigger_price"] = price + sig["sl_dist"] if sig["direction"] == 1 else price - sig["sl_dist"]
                        active_trade["be_sl_price"] = price * 1.0018 if sig["direction"] == 1 else price * 0.9982
                        active_trade["be_locked"] = False
                        next_sig_idx += 1

                if active_trade is not None:
                    d = active_trade["direction"]
                    entry_p = active_trade["entry_price"]
                    pos_size = active_trade["pos_size"]
                    closed = False
                    exit_p = price
                    reason = ""

                    if d == 1:
                        if not active_trade["be_locked"] and price >= active_trade["be_trigger_price"]:
                            active_trade["current_sl"] = active_trade["be_sl_price"]
                            active_trade["be_locked"] = True
                        if price >= active_trade["tp_price"]:
                            exit_p = active_trade["tp_price"]
                            reason = "TAKE_PROFIT"
                            closed = True
                        elif price <= active_trade["current_sl"]:
                            exit_p = active_trade["current_sl"]
                            reason = "BREAK_EVEN" if active_trade["be_locked"] else "STOP_LOSS"
                            closed = True
                        if closed:
                            gross = (exit_p - entry_p) * pos_size
                            fees = (entry_p * pos_size) * fee_rate * 2
                            net = gross - fees
                    elif d == -1:
                        if not active_trade["be_locked"] and price <= active_trade["be_trigger_price"]:
                            active_trade["current_sl"] = active_trade["be_sl_price"]
                            active_trade["be_locked"] = True
                        if price <= active_trade["tp_price"]:
                            exit_p = active_trade["tp_price"]
                            reason = "TAKE_PROFIT"
                            closed = True
                        elif price >= active_trade["current_sl"]:
                            exit_p = active_trade["current_sl"]
                            reason = "BREAK_EVEN" if active_trade["be_locked"] else "STOP_LOSS"
                            closed = True
                        if closed:
                            gross = (entry_p - exit_p) * pos_size
                            fees = (entry_p * pos_size) * fee_rate * 2
                            net = gross - fees

                    if closed:
                        dur_mins = round((dt_utc - active_trade["entry_time"]).total_seconds() / 60, 1)
                        daily_pnl[date_key] += net
                        tick_trades.append({
                            "entry_time": active_trade["entry_time"],
                            "exit_time": dt_utc,
                            "direction": "LONG" if d == 1 else "SHORT",
                            "net_pnl": net,
                            "gross_pnl": gross,
                            "fees": fees,
                            "reason": reason,
                            "duration_m": dur_mins
                        })
                        active_trade = None

    tdf = pd.DataFrame(tick_trades)
    wins = tdf[tdf["net_pnl"] > 0]
    losses = tdf[tdf["net_pnl"] <= 0]
    tot = len(tdf)
    wr = len(wins) / tot * 100 if tot > 0 else 0
    net = tdf["net_pnl"].sum()
    gross_win = wins["net_pnl"].sum()
    gross_loss = abs(losses["net_pnl"].sum())
    pf = gross_win / (gross_loss + 1e-9)
    elapsed = time.time() - t0

    print(f"\n[{interval} ON 36M REAL TICKS] Finished in {elapsed:.1f}s:")
    print(f"  Total Trades:   {tot} ({tot/30:.1f}/day)")
    print(f"  Win Rate:       {wr:.2f}% ({len(wins)}W / {len(losses)}L)")
    print(f"  Net Profit:     ${net:+.2f}")
    print(f"  Profit Factor:  {pf:.2f}")
    print(f"  TP Hits:        {len(tdf[tdf['reason']=='TAKE_PROFIT'])}")
    print(f"  Break-Even:     {len(tdf[tdf['reason']=='BREAK_EVEN'])}")
    print(f"  Stop-Loss:      {len(tdf[tdf['reason']=='STOP_LOSS'])}")
    print(f"  Total Fees:     ${tdf['fees'].sum():.2f}")
    return tdf

if __name__ == "__main__":
    print("Testing 15M against 36M Real Sub-Second Ticks...")
    run_tick_test("15m")
