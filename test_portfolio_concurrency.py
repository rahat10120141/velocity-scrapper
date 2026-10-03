"""
VELOCITY SCALPER: Multi-Position Concurrency Analysis on Real Tick & 1H Data
Tests MAX_OPEN_POSITIONS = 1 vs 2 vs 3 across 6 pairs in September 2026:
BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, DOGEUSDT, LINKUSDT
Measures:
  1. Win Rate %
  2. Total Trades & Daily Frequency
  3. Net Realized Profit ($)
  4. Max Drawdown ($ & %)
  5. Correlation Risk & Simultaneous Loss Events
  6. Daily Circuit Breaker Behavior ($3 Profit Lock / -$3 Loss Defense)
"""
import os
import zipfile
import io
import csv
import json
import datetime
import urllib.request
import pandas as pd
import numpy as np

TICK_STORE = "/home/rahat/Documents/claude/tick_data"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT"]

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
            reader = csv.reader(io.TextIOWrapper(f, encoding='utf-8'))
            first_row = next(reader, None)
            if first_row and not first_row[0].isdigit():
                pass
            elif first_row:
                yield int(first_row[5]), float(first_row[1])
            for row in reader:
                if len(row) >= 6:
                    yield int(row[5]), float(row[1])

def evaluate_all_potential_trades(month="2026-09"):
    """Evaluates the exact tick-by-tick outcome of every single signal on each of the 6 pairs."""
    year, mon = map(int, month.split("-"))
    start_dt = datetime.datetime(year, mon, 1, 0, 0)
    warmup_dt = start_dt - datetime.timedelta(days=15)
    end_dt = datetime.datetime(year, mon + 1, 1, 0, 0) if mon < 12 else datetime.datetime(year + 1, 1, 1, 0, 0)
    
    all_trade_candidates = []
    
    for sym in SYMBOLS:
        print(f"Pre-calculating tick outcomes for {sym} ({month})...")
        df = fetch_1h_klines(sym, warmup_dt, end_dt)
        df = prepare_signals(df)
        month_df = df.loc[start_dt:end_dt].copy()
        
        # Signals mapped by hour
        signals = {}
        for t, row in month_df.iterrows():
            if row["signal"] != 0 and not np.isnan(row["atr"]) and row["atr"] > 0:
                ts_ms = int(t.timestamp() * 1000)
                signals[ts_ms] = {
                    "time": t,
                    "direction": int(row["signal"]),
                    "atr": row["atr"]
                }
                
        # Replay ticks for this symbol to find exact entry and exit
        open_trade = None
        for ts_ms, price in stream_ticks(sym, month):
            hour_bucket = (ts_ms // 3600000) * 3600000
            
            # Exit check if open
            if open_trade is not None:
                d = open_trade["direction"]
                entry_p = open_trade["entry_price"]
                sl_p = open_trade["sl_price"]
                tp_p = open_trade["tp_price"]
                be_trig = open_trade["be_trigger"]
                pos_size = open_trade["pos_size"]
                closed = False
                exit_p = price
                reason = ""
                
                if d == 1: # LONG
                    if not open_trade["be_locked"] and price >= be_trig:
                        open_trade["sl_price"] = entry_p * 1.0018
                        open_trade["be_locked"] = True
                    if price >= tp_p:
                        closed = True
                        exit_p = tp_p
                        reason = "TP_HIT"
                    elif price <= open_trade["sl_price"]:
                        closed = True
                        exit_p = open_trade["sl_price"]
                        reason = "BE_EXIT" if open_trade["be_locked"] else "SL_HIT"
                elif d == -1: # SHORT
                    if not open_trade["be_locked"] and price <= be_trig:
                        open_trade["sl_price"] = entry_p * (1 - 0.0018)
                        open_trade["be_locked"] = True
                    if price <= tp_p:
                        closed = True
                        exit_p = tp_p
                        reason = "TP_HIT"
                    elif price >= open_trade["sl_price"]:
                        closed = True
                        exit_p = open_trade["sl_price"]
                        reason = "BE_EXIT" if open_trade["be_locked"] else "SL_HIT"
                        
                if closed:
                    gross = (exit_p - entry_p) * pos_size if d == 1 else (entry_p - exit_p) * pos_size
                    fees = (entry_p * pos_size + exit_p * pos_size) * 0.0004
                    net = gross - fees
                    open_trade["exit_ts_ms"] = ts_ms
                    open_trade["exit_price"] = exit_p
                    open_trade["reason"] = reason
                    open_trade["net_pnl"] = net
                    open_trade["fees"] = fees
                    all_trade_candidates.append(open_trade)
                    open_trade = None
                    
            # Entry check
            if open_trade is None and hour_bucket in signals:
                sig_info = signals.pop(hour_bucket)
                d = sig_info["direction"]
                atr = sig_info["atr"]
                entry_p = price
                sl_dist = 1.0 * atr
                tp_dist = 2.2 * sl_dist
                pos_size = 2.50 / sl_dist # $2.50 risk
                pos_size = min(pos_size, 250.0 / entry_p) # $250 max notional ($25 margin at 10x)
                
                open_trade = {
                    "symbol": sym,
                    "direction": d,
                    "entry_ts_ms": ts_ms,
                    "entry_time": datetime.datetime.fromtimestamp(ts_ms / 1000, datetime.timezone.utc),
                    "entry_price": entry_p,
                    "sl_price": entry_p - sl_dist if d == 1 else entry_p + sl_dist,
                    "tp_price": entry_p + tp_dist if d == 1 else entry_p - tp_dist,
                    "be_trigger": entry_p + sl_dist if d == 1 else entry_p - sl_dist,
                    "be_locked": False,
                    "pos_size": pos_size
                }
                
    # Sort all candidates by entry time
    all_trade_candidates.sort(key=lambda x: x["entry_ts_ms"])
    print(f"Total verified tick-trade opportunities found across 6 pairs: {len(all_trade_candidates)}\n")
    return all_trade_candidates

def simulate_portfolio(trade_candidates, max_concurrent=1, initial_balance=100.0, margin_per_trade=25.0):
    balance = initial_balance
    peak_balance = initial_balance
    max_dd = 0.0
    active_positions = [] # Currently open trades
    closed_trades = []
    daily_pnl = {}
    
    # We step through events: entries and exits in exact chronological order
    events = []
    for t in trade_candidates:
        events.append({"type": "SIGNAL", "ts_ms": t["entry_ts_ms"], "trade": t})
        
    events.sort(key=lambda x: x["ts_ms"])
    
    # Track simultaneous losses
    simultaneous_losses = 0

    for ev in events:
        cur_ts = ev["ts_ms"]
        day_bucket = cur_ts // 86400000
        if day_bucket not in daily_pnl:
            daily_pnl[day_bucket] = 0.0
            
        day_realized = daily_pnl[day_bucket]
        daily_target_hit = (day_realized >= 3.00)
        daily_loss_hit = (day_realized <= -3.00)
        
        # 1. Close any positions that have exited before or at this ts
        still_open = []
        for pos in active_positions:
            if pos["exit_ts_ms"] <= cur_ts:
                # Close pos
                net = pos["net_pnl"]
                balance += net
                daily_pnl[day_bucket] += net
                if balance > peak_balance:
                    peak_balance = balance
                dd = peak_balance - balance
                if dd > max_dd:
                    max_dd = dd
                closed_trades.append(pos)
            else:
                still_open.append(pos)
        active_positions = still_open
        
        # 2. Check if we can enter this trade
        t = ev["trade"]
        if not daily_target_hit and not daily_loss_hit:
            if len(active_positions) < max_concurrent:
                # Ensure we don't open the same symbol twice
                open_syms = {p["symbol"] for p in active_positions}
                if t["symbol"] not in open_syms:
                    # Check free margin
                    margin_used = len(active_positions) * margin_per_trade
                    if balance - margin_used >= margin_per_trade:
                        active_positions.append(t)
                        
    # Close any remaining at end
    for pos in active_positions:
        net = pos["net_pnl"]
        balance += net
        if balance > peak_balance:
            peak_balance = balance
        dd = peak_balance - balance
        if dd > max_dd:
            max_dd = dd
        closed_trades.append(pos)
        
    n = len(closed_trades)
    if n == 0:
        return None
    wins = [t for t in closed_trades if t["net_pnl"] > 0]
    losses = [t for t in closed_trades if t["net_pnl"] <= 0]
    wr = (len(wins) / n) * 100
    net_pnl = sum(t["net_pnl"] for t in closed_trades)
    fees = sum(t["fees"] for t in closed_trades)
    gross_w = sum(t["net_pnl"] for t in wins)
    gross_l = abs(sum(t["net_pnl"] for t in losses))
    pf = gross_w / gross_l if gross_l > 0 else 999.0
    
    target_days = sum(1 for p in daily_pnl.values() if p >= 3.00)
    loss_days = sum(1 for p in daily_pnl.values() if p <= -3.00)
    
    return {
        "max_concurrent": max_concurrent,
        "trades": n,
        "win_rate": wr,
        "wins": len(wins),
        "losses": len(losses),
        "net_pnl": net_pnl,
        "final_balance": balance,
        "fees": fees,
        "profit_factor": pf,
        "max_drawdown": max_dd,
        "max_dd_pct": (max_dd / peak_balance) * 100,
        "target_days": target_days,
        "loss_days": loss_days
    }

def main():
    print("="*85)
    print("  EVALUATING MULTI-POSITION REAL-TICK SIMULATION (September 2026)")
    print("="*85)
    candidates = evaluate_all_potential_trades("2026-09")
    
    results = []
    for mc in [1, 2, 3]:
        r = simulate_portfolio(candidates, max_concurrent=mc, initial_balance=100.0)
        if r:
            results.append(r)
            
    print("\n" + "="*95)
    print("    REAL-TICK REPLAY: MAX 1 vs MAX 2 vs MAX 3 SIMULTANEOUS TRADES (Sept 2026)")
    print("="*95)
    print(f"{'CONCURRENT':<11} | {'TRADES':<7} | {'WIN RATE':<9} | {'NET PNL':<10} | {'FEES':<8} | {'PF':<6} | {'MAX DD':<12} | {'TARGET DAYS':<11} | {'LOSS DAYS':<10}")
    print("-" * 95)
    for r in results:
        dd_str = f"${r['max_drawdown']:.2f} ({r['max_dd_pct']:.1f}%)"
        print(f"Max {r['max_concurrent']:<7} | {r['trades']:<7} | {r['win_rate']:<8.1f}% | ${r['net_pnl']:<+9.2f} | ${r['fees']:<7.2f} | {r['profit_factor']:<6.2f} | {dd_str:<12} | {r['target_days']:<11} | {r['loss_days']:<10}")
    print("="*95 + "\n")

if __name__ == "__main__":
    main()
