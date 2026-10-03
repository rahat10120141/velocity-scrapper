"""
VELOCITY SCALPER: Multi-Month Concurrency Audit (2026-04 to 2026-09)
Evaluates 2 concurrent slots vs 3 concurrent slots across 6 months of authentic Binance tick data
Store: /home/rahat/Documents/claude/tick_data
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
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]

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

def evaluate_month_candidates(month):
    year, mon = map(int, month.split("-"))
    start_dt = datetime.datetime(year, mon, 1, 0, 0)
    warmup_dt = start_dt - datetime.timedelta(days=15)
    end_dt = datetime.datetime(year, mon + 1, 1, 0, 0) if mon < 12 else datetime.datetime(year + 1, 1, 1, 0, 0)
    
    candidates = []
    for sym in SYMBOLS:
        df = fetch_1h_klines(sym, warmup_dt, end_dt)
        df = prepare_signals(df)
        month_df = df.loc[start_dt:end_dt].copy()
        
        signals = {}
        for t, row in month_df.iterrows():
            if row["signal"] != 0 and not np.isnan(row["atr"]) and row["atr"] > 0:
                ts_ms = int(t.timestamp() * 1000)
                signals[ts_ms] = {
                    "time": t,
                    "direction": int(row["signal"]),
                    "atr": row["atr"]
                }
                
        open_trade = None
        for ts_ms, price in stream_ticks(sym, month):
            hour_bucket = (ts_ms // 3600000) * 3600000
            if open_trade is not None:
                d = open_trade["direction"]
                entry_p = open_trade["entry_price"]
                pos_size = open_trade["pos_size"]
                closed = False
                exit_p = price
                reason = ""
                
                if d == 1:
                    if not open_trade["be_locked"] and price >= open_trade["be_trigger"]:
                        open_trade["sl_price"] = entry_p * 1.0018
                        open_trade["be_locked"] = True
                    if price >= open_trade["tp_price"]:
                        closed = True
                        exit_p = open_trade["tp_price"]
                        reason = "TP_HIT"
                    elif price <= open_trade["sl_price"]:
                        closed = True
                        exit_p = open_trade["sl_price"]
                        reason = "BE_EXIT" if open_trade["be_locked"] else "SL_HIT"
                elif d == -1:
                    if not open_trade["be_locked"] and price <= open_trade["be_trigger"]:
                        open_trade["sl_price"] = entry_p * (1 - 0.0018)
                        open_trade["be_locked"] = True
                    if price <= open_trade["tp_price"]:
                        closed = True
                        exit_p = open_trade["tp_price"]
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
                    candidates.append(open_trade)
                    open_trade = None
                    
            if open_trade is None and hour_bucket in signals:
                sig_info = signals.pop(hour_bucket)
                d = sig_info["direction"]
                atr = sig_info["atr"]
                entry_p = price
                sl_dist = 1.0 * atr
                tp_dist = 2.2 * sl_dist
                pos_size = 2.50 / sl_dist
                pos_size = min(pos_size, 250.0 / entry_p)
                
                open_trade = {
                    "symbol": sym,
                    "direction": d,
                    "entry_ts_ms": ts_ms,
                    "entry_price": entry_p,
                    "sl_price": entry_p - sl_dist if d == 1 else entry_p + sl_dist,
                    "tp_price": entry_p + tp_dist if d == 1 else entry_p - tp_dist,
                    "be_trigger": entry_p + sl_dist if d == 1 else entry_p - sl_dist,
                    "be_locked": False,
                    "pos_size": pos_size
                }
    candidates.sort(key=lambda x: x["entry_ts_ms"])
    return candidates

def simulate_portfolio(trade_candidates, max_concurrent=2, initial_balance=100.0):
    balance = initial_balance
    peak_balance = initial_balance
    max_dd = 0.0
    active_positions = []
    closed_trades = []
    daily_pnl = {}
    
    events = []
    for t in trade_candidates:
        events.append({"type": "SIGNAL", "ts_ms": t["entry_ts_ms"], "trade": t})
    events.sort(key=lambda x: x["ts_ms"])
    
    target_days = 0
    loss_days = 0
    evaluated_days = set()

    for ev in events:
        cur_ts = ev["ts_ms"]
        day_bucket = cur_ts // 86400000
        if day_bucket not in daily_pnl:
            daily_pnl[day_bucket] = 0.0
            
        day_realized = daily_pnl[day_bucket]
        daily_target_hit = (day_realized >= 3.00)
        daily_loss_hit = (day_realized <= -3.00)
        
        still_open = []
        for pos in active_positions:
            if pos["exit_ts_ms"] <= cur_ts:
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
        
        if len(active_positions) < max_concurrent and not daily_target_hit and not daily_loss_hit:
            cand = ev["trade"]
            open_symbols = {p["symbol"] for p in active_positions}
            if cand["symbol"] not in open_symbols:
                active_positions.append(cand)
                
    # Close any remaining
    for pos in active_positions:
        net = pos["net_pnl"]
        balance += net
        if balance > peak_balance: peak_balance = balance
        dd = peak_balance - balance
        if dd > max_dd: max_dd = dd
        closed_trades.append(pos)
        
    tot = len(closed_trades)
    wins = [t for t in closed_trades if t["net_pnl"] > 0]
    wr = len(wins) / tot * 100 if tot > 0 else 0
    net_pnl = balance - initial_balance
    fees = sum(t["fees"] for t in closed_trades)
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in closed_trades if t["net_pnl"] <= 0))
    pf = gross_win / (gross_loss + 1e-9)
    
    for d, p in daily_pnl.items():
        if p >= 3.00: target_days += 1
        elif p <= -3.00: loss_days += 1
        
    return {
        "trades": tot,
        "win_rate": round(wr, 1),
        "net_pnl": round(net_pnl, 2),
        "fees": round(fees, 2),
        "pf": round(pf, 2),
        "max_dd": round(max_dd, 2),
        "target_days": target_days,
        "loss_days": loss_days
    }

if __name__ == "__main__":
    print("=" * 95)
    print("  VELOCITY SCALPER: 6-MONTH TICK CONCURRENCY AUDIT (2026-04 to 2026-09)")
    print("  Testing MAX_OPEN_POSITIONS = 2 vs MAX_OPEN_POSITIONS = 3 across 6 Pairs")
    print("=" * 95)
    
    all_month_results_2 = []
    all_month_results_3 = []
    
    for m in MONTHS:
        print(f"\n>>> Processing Month: {m} across 6 Crypto Pairs...")
        cands = evaluate_month_candidates(m)
        print(f"    Total tick candidates in {m}: {len(cands)}")
        
        res2 = simulate_portfolio(cands, max_concurrent=2)
        res3 = simulate_portfolio(cands, max_concurrent=3)
        res2["month"] = m
        res3["month"] = m
        all_month_results_2.append(res2)
        all_month_results_3.append(res3)
        
        print(f"    Slot 2: {res2['trades']} trades | WR {res2['win_rate']}% | Net: ${res2['net_pnl']:+.2f} | PF: {res2['pf']} | MaxDD: ${res2['max_dd']:.2f}")
        print(f"    Slot 3: {res3['trades']} trades | WR {res3['win_rate']}% | Net: ${res3['net_pnl']:+.2f} | PF: {res3['pf']} | MaxDD: ${res3['max_dd']:.2f}")

    print("\n" + "=" * 95)
    print("              FINAL 6-MONTH TICK REPLAY SUMMARY: 2 SLOTS vs 3 SLOTS")
    print("=" * 95)
    print(f"{'MONTH':<10} | {'TRADES (2s vs 3s)':<18} | {'WIN RATE (2s vs 3s)':<20} | {'NET PNL (2s vs 3s)':<22} | {'PF (2s vs 3s)':<15}")
    print("-" * 95)
    for r2, r3 in zip(all_month_results_2, all_month_results_3):
        m = r2["month"]
        t_str = f"{r2['trades']} vs {r3['trades']}"
        wr_str = f"{r2['win_rate']}% vs {r3['win_rate']}%"
        pnl_str = f"${r2['net_pnl']:+.2f} vs ${r3['net_pnl']:+.2f}"
        pf_str = f"{r2['pf']} vs {r3['pf']}"
        print(f"{m:<10} | {t_str:<18} | {wr_str:<20} | {pnl_str:<22} | {pf_str:<15}")
    print("-" * 95)
    
    tot_trades_2 = sum(r["trades"] for r in all_month_results_2)
    tot_trades_3 = sum(r["trades"] for r in all_month_results_3)
    tot_pnl_2 = sum(r["net_pnl"] for r in all_month_results_2)
    tot_pnl_3 = sum(r["net_pnl"] for r in all_month_results_3)
    avg_wr_2 = np.mean([r["win_rate"] for r in all_month_results_2])
    avg_wr_3 = np.mean([r["win_rate"] for r in all_month_results_3])
    tot_targets_2 = sum(r["target_days"] for r in all_month_results_2)
    tot_targets_3 = sum(r["target_days"] for r in all_month_results_3)
    tot_fees_2 = sum(r["fees"] for r in all_month_results_2)
    tot_fees_3 = sum(r["fees"] for r in all_month_results_3)
    
    print(f"{'TOTAL 6-MO':<10} | {f'{tot_trades_2} vs {tot_trades_3}':<18} | {f'{avg_wr_2:.1f}% vs {avg_wr_3:.1f}%':<20} | {f'${tot_pnl_2:+.2f} vs ${tot_pnl_3:+.2f}':<22} |")
    print(f"Total Fees: 2 Slots = ${tot_fees_2:.2f} | 3 Slots = ${tot_fees_3:.2f}")
    print(f"Target Hit Days ($3.00 profit lock): 2 Slots = {tot_targets_2} days | 3 Slots = {tot_targets_3} days")
    print("=" * 95)

