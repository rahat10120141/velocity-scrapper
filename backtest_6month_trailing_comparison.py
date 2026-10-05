"""
VELOCITY SCALPER: 6-Month Real-Tick Backtest & Trailing Stop Optimization
Compares Baseline (No Trailing, Static 1.0R BE) against 3 Dynamic Trailing Stop Strategies
across 600+ Million authentic Binance sub-second ticks (April 2026 to September 2026).
"""
import os
import io
import csv
import zipfile
import datetime
import urllib.request
import json
import time
import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor

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

def evaluate_month_multi_strategy(month):
    """
    Evaluates 4 strategies concurrently on the exact same tick stream for a given month.
    """
    year, mon = map(int, month.split("-"))
    start_dt = datetime.datetime(year, mon, 1, 0, 0)
    warmup_dt = start_dt - datetime.timedelta(days=15)
    end_dt = datetime.datetime(year, mon + 1, 1, 0, 0) if mon < 12 else datetime.datetime(year + 1, 1, 1, 0, 0)
    
    # Store candidates for each strategy
    strat_candidates = {
        "Baseline": [],
        "Strat1_TightTrail": [],
        "Strat2_BalancedTrail": [],
        "Strat3_ATRAdaptive": []
    }
    
    for sym in SYMBOLS:
        df = fetch_1h_klines(sym, warmup_dt, end_dt)
        df = prepare_signals(df)
        month_df = df.loc[start_dt:end_dt].copy()
        
        # Build signals dictionary
        raw_signals = {}
        for t, row in month_df.iterrows():
            if row["signal"] != 0 and not np.isnan(row["atr"]) and row["atr"] > 0:
                ts_ms = int(t.timestamp() * 1000)
                raw_signals[ts_ms] = {
                    "time": t,
                    "direction": int(row["signal"]),
                    "atr": row["atr"]
                }
                
        # Each strategy has its own active trade slot
        active_trades = {
            "Baseline": None,
            "Strat1_TightTrail": None,
            "Strat2_BalancedTrail": None,
            "Strat3_ATRAdaptive": None
        }
        
        # We need independent signal queues for each strategy
        sig_queues = {k: dict(raw_signals) for k in active_trades}
        
        for ts_ms, price in stream_ticks(sym, month):
            hour_bucket = (ts_ms // 3600000) * 3600000
            
            # Update all active trades
            for strat_key, trade in active_trades.items():
                if trade is not None:
                    d = trade["direction"]
                    entry_p = trade["entry_price"]
                    pos_size = trade["pos_size"]
                    atr = trade["atr"]
                    sl_dist = trade["sl_dist"]
                    closed = False
                    exit_p = price
                    reason = ""
                    
                    # Track extreme price
                    if d == 1:
                        if price > trade["highest_p"]:
                            trade["highest_p"] = price
                        highest_p = trade["highest_p"]
                        gain_pct = (highest_p - entry_p) / entry_p
                        gain_r = (highest_p - entry_p) / sl_dist if sl_dist > 0 else 0
                        
                        # --- STRATEGY SPECIFIC LOGIC ---
                        if strat_key == "Baseline":
                            # Static 1.0R BE, no trailing
                            if not trade["be_locked"] and price >= trade["be_trigger"]:
                                trade["sl_price"] = entry_p * 1.0018
                                trade["be_locked"] = True
                        
                        elif strat_key == "Strat1_TightTrail":
                            # Fee shield at +0.22%, Trail 0.20% behind peak starting at +0.40%
                            if not trade["be_locked"] and gain_pct >= 0.0022:
                                be_sl = entry_p * 1.0010
                                if be_sl > trade["sl_price"]:
                                    trade["sl_price"] = be_sl
                                trade["be_locked"] = True
                            if gain_pct >= 0.0040:
                                trade["trail_active"] = True
                                trail_sl = highest_p * (1.0 - 0.0020)
                                if trail_sl > trade["sl_price"]:
                                    trade["sl_price"] = trail_sl
                                    
                        elif strat_key == "Strat2_BalancedTrail":
                            # Fee shield at +0.25%, Trail 0.28% behind peak starting at +0.50%
                            if not trade["be_locked"] and gain_pct >= 0.0025:
                                be_sl = entry_p * 1.0010
                                if be_sl > trade["sl_price"]:
                                    trade["sl_price"] = be_sl
                                trade["be_locked"] = True
                            if gain_pct >= 0.0050:
                                trade["trail_active"] = True
                                trail_sl = highest_p * (1.0 - 0.0028)
                                if trail_sl > trade["sl_price"]:
                                    trade["sl_price"] = trail_sl
                                    
                        elif strat_key == "Strat3_ATRAdaptive":
                            # Fee shield at 0.35 ATR, Trail 0.35 ATR behind peak starting at 0.70 ATR
                            if not trade["be_locked"] and gain_r >= 0.35:
                                be_sl = entry_p * 1.0012
                                if be_sl > trade["sl_price"]:
                                    trade["sl_price"] = be_sl
                                trade["be_locked"] = True
                            if gain_r >= 0.70:
                                trade["trail_active"] = True
                                trail_sl = highest_p - (0.35 * sl_dist)
                                if trail_sl > trade["sl_price"]:
                                    trade["sl_price"] = trail_sl
                                    
                        # Check Exits for LONG
                        if price >= trade["tp_price"]:
                            closed = True
                            exit_p = trade["tp_price"]
                            reason = "TP_HIT"
                        elif price <= trade["sl_price"]:
                            closed = True
                            exit_p = trade["sl_price"]
                            if trade.get("trail_active"):
                                reason = "TRAIL_EXIT"
                            elif trade["be_locked"]:
                                reason = "BE_EXIT"
                            else:
                                reason = "SL_HIT"

                    elif d == -1:
                        if price < trade["lowest_p"]:
                            trade["lowest_p"] = price
                        lowest_p = trade["lowest_p"]
                        gain_pct = (entry_p - lowest_p) / entry_p
                        gain_r = (entry_p - lowest_p) / sl_dist if sl_dist > 0 else 0
                        
                        # --- STRATEGY SPECIFIC LOGIC ---
                        if strat_key == "Baseline":
                            if not trade["be_locked"] and price <= trade["be_trigger"]:
                                trade["sl_price"] = entry_p * (1.0 - 0.0018)
                                trade["be_locked"] = True
                                
                        elif strat_key == "Strat1_TightTrail":
                            if not trade["be_locked"] and gain_pct >= 0.0022:
                                be_sl = entry_p * (1.0 - 0.0010)
                                if be_sl < trade["sl_price"]:
                                    trade["sl_price"] = be_sl
                                trade["be_locked"] = True
                            if gain_pct >= 0.0040:
                                trade["trail_active"] = True
                                trail_sl = lowest_p * (1.0 + 0.0020)
                                if trail_sl < trade["sl_price"]:
                                    trade["sl_price"] = trail_sl
                                    
                        elif strat_key == "Strat2_BalancedTrail":
                            if not trade["be_locked"] and gain_pct >= 0.0025:
                                be_sl = entry_p * (1.0 - 0.0010)
                                if be_sl < trade["sl_price"]:
                                    trade["sl_price"] = be_sl
                                trade["be_locked"] = True
                            if gain_pct >= 0.0050:
                                trade["trail_active"] = True
                                trail_sl = lowest_p * (1.0 + 0.0028)
                                if trail_sl < trade["sl_price"]:
                                    trade["sl_price"] = trail_sl
                                    
                        elif strat_key == "Strat3_ATRAdaptive":
                            if not trade["be_locked"] and gain_r >= 0.35:
                                be_sl = entry_p * (1.0 - 0.0012)
                                if be_sl < trade["sl_price"]:
                                    trade["sl_price"] = be_sl
                                trade["be_locked"] = True
                            if gain_r >= 0.70:
                                trade["trail_active"] = True
                                trail_sl = lowest_p + (0.35 * sl_dist)
                                if trail_sl < trade["sl_price"]:
                                    trade["sl_price"] = trail_sl
                                    
                        # Check Exits for SHORT
                        if price <= trade["tp_price"]:
                            closed = True
                            exit_p = trade["tp_price"]
                            reason = "TP_HIT"
                        elif price >= trade["sl_price"]:
                            closed = True
                            exit_p = trade["sl_price"]
                            if trade.get("trail_active"):
                                reason = "TRAIL_EXIT"
                            elif trade["be_locked"]:
                                reason = "BE_EXIT"
                            else:
                                reason = "SL_HIT"
                                
                    if closed:
                        gross = (exit_p - entry_p) * pos_size if d == 1 else (entry_p - exit_p) * pos_size
                        fees = (entry_p * pos_size + exit_p * pos_size) * 0.0004
                        net = gross - fees
                        trade["exit_ts_ms"] = ts_ms
                        trade["exit_price"] = exit_p
                        trade["reason"] = reason
                        trade["net_pnl"] = net
                        trade["fees"] = fees
                        strat_candidates[strat_key].append(trade)
                        active_trades[strat_key] = None
                        
                # Check for new entry if no active trade in this strategy
                if active_trades[strat_key] is None and hour_bucket in sig_queues[strat_key]:
                    sig_info = sig_queues[strat_key].pop(hour_bucket)
                    d = sig_info["direction"]
                    atr = sig_info["atr"]
                    entry_p = price
                    sl_dist = 1.0 * atr
                    tp_dist = 2.2 * sl_dist
                    pos_size = 2.50 / sl_dist
                    pos_size = min(pos_size, 250.0 / entry_p)
                    
                    active_trades[strat_key] = {
                        "symbol": sym,
                        "direction": d,
                        "entry_ts_ms": ts_ms,
                        "entry_price": entry_p,
                        "atr": atr,
                        "sl_dist": sl_dist,
                        "highest_p": entry_p,
                        "lowest_p": entry_p,
                        "sl_price": entry_p - sl_dist if d == 1 else entry_p + sl_dist,
                        "tp_price": entry_p + tp_dist if d == 1 else entry_p - tp_dist,
                        "be_trigger": entry_p + sl_dist if d == 1 else entry_p - sl_dist,
                        "be_locked": False,
                        "trail_active": False,
                        "pos_size": pos_size
                    }

    # Sort each strategy's candidates by entry time
    for k in strat_candidates:
        strat_candidates[k].sort(key=lambda x: x["entry_ts_ms"])
        
    return strat_candidates

def simulate_portfolio(trade_candidates, max_concurrent=3, initial_balance=100.0):
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
    
    # Reasons breakdown
    reasons = {}
    for t in closed_trades:
        r = t.get("reason", "OTHER")
        reasons[r] = reasons.get(r, 0) + 1
        
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
        "loss_days": loss_days,
        "reasons": reasons
    }

def process_single_month(month):
    t0 = time.time()
    cands_dict = evaluate_month_multi_strategy(month)
    month_res = {}
    for strat_key, cands in cands_dict.items():
        sim_res = simulate_portfolio(cands, max_concurrent=3)
        sim_res["candidate_count"] = len(cands)
        month_res[strat_key] = sim_res
    elapsed = round(time.time() - t0, 1)
    return month, month_res, elapsed

if __name__ == "__main__":
    print("=" * 105)
    print("   VELOCITY SCALPER: 6-MONTH TICK AUDIT & TRAILING STOP COMPARISON (APR-SEP 2026)")
    print("   Replaying 600+ Million Authentic Binance Sub-Second Ticks across 6 Pairs")
    print("   Comparing 4 Strategies Side-by-Side on the Exact Same Market Conditions")
    print("=" * 105)
    
    t_global = time.time()
    with ProcessPoolExecutor(max_workers=6) as executor:
        all_results = list(executor.map(process_single_month, MONTHS))
        
    # Reorganize by month
    results_by_month = {m: res for m, res, _ in all_results}
    
    strategies = ["Baseline", "Strat1_TightTrail", "Strat2_BalancedTrail", "Strat3_ATRAdaptive"]
    strat_labels = {
        "Baseline": "1. Baseline (Current: Static 1.0R BE, No Trail)",
        "Strat1_TightTrail": "2. Tight Trailing (Shield +0.22%, Trail 0.20% @ +0.40%)",
        "Strat2_BalancedTrail": "3. Balanced Trailing (Shield +0.25%, Trail 0.28% @ +0.50%)",
        "Strat3_ATRAdaptive": "4. ATR-Adaptive Trailing (Shield 0.35 ATR, Trail 0.35 ATR @ 0.70 ATR)"
    }
    
    print("\n" + "=" * 105)
    print("MONTH-BY-MONTH NET PROFIT & WIN RATE COMPARISON ($100 Starting Capital, 3 Slots)")
    print("=" * 105)
    print(f"{'MONTH':<10} | {'1. BASELINE':<20} | {'2. TIGHT TRAIL':<20} | {'3. BALANCED TRAIL':<20} | {'4. ATR-ADAPTIVE':<20}")
    print("-" * 105)
    
    for m in MONTHS:
        row = results_by_month[m]
        def fmt(s):
            d = row[s]
            return f"${d['net_pnl']:>+7.2f} ({d['win_rate']:>4.1f}%, {d['trades']}t)"
        print(f"{m:<10} | {fmt('Baseline'):<20} | {fmt('Strat1_TightTrail'):<20} | {fmt('Strat2_BalancedTrail'):<20} | {fmt('Strat3_ATRAdaptive'):<20}")
        
    print("=" * 105)
    print("\n" + "=" * 105)
    print("                      FULL 6-MONTH AGGREGATE PERFORMANCE SUMMARY")
    print("=" * 105)
    print(f"{'METRIC':<30} | {'1. BASELINE':<16} | {'2. TIGHT TRAIL':<16} | {'3. BALANCED TRAIL':<18} | {'4. ATR-ADAPTIVE':<16}")
    print("-" * 105)
    
    agg = {}
    for s in strategies:
        tot_trades = sum(results_by_month[m][s]["trades"] for m in MONTHS)
        tot_pnl = sum(results_by_month[m][s]["net_pnl"] for m in MONTHS)
        tot_fees = sum(results_by_month[m][s]["fees"] for m in MONTHS)
        avg_wr = np.mean([results_by_month[m][s]["win_rate"] for m in MONTHS])
        max_dd = max([results_by_month[m][s]["max_dd"] for m in MONTHS])
        tot_targets = sum(results_by_month[m][s]["target_days"] for m in MONTHS)
        tot_loss_days = sum(results_by_month[m][s]["loss_days"] for m in MONTHS)
        
        # Combine reasons
        all_reasons = {}
        for m in MONTHS:
            for r, count in results_by_month[m][s]["reasons"].items():
                all_reasons[r] = all_reasons.get(r, 0) + count
                
        agg[s] = {
            "trades": tot_trades,
            "pnl": tot_pnl,
            "fees": tot_fees,
            "wr": avg_wr,
            "max_dd": max_dd,
            "targets": tot_targets,
            "loss_days": tot_loss_days,
            "reasons": all_reasons
        }
        
    def get_agg_row(title, key, fmt_str):
        vals = [fmt_str(agg[s][key]) for s in strategies]
        return f"{title:<30} | {vals[0]:<16} | {vals[1]:<16} | {vals[2]:<18} | {vals[3]:<16}"
        
    print(get_agg_row("Total 6M Net Profit ($)", "pnl", lambda v: f"${v:>+8.2f}"))
    print(get_agg_row("Return on $100 Account", "pnl", lambda v: f"+{v:.1f}%"))
    print(get_agg_row("Average Monthly Net ($)", "pnl", lambda v: f"${v/6:>+8.2f}/mo"))
    print(get_agg_row("Average Win Rate (%)", "wr", lambda v: f"{v:>6.1f}%"))
    print(get_agg_row("Total Completed Trades", "trades", lambda v: f"{v:>6d}"))
    print(get_agg_row("Max Monthly Drawdown ($)", "max_dd", lambda v: f"${v:>7.2f}"))
    print(get_agg_row("Total Fees Paid ($)", "fees", lambda v: f"${v:>7.2f}"))
    print(get_agg_row("Target Hit Days ($3 Lock)", "targets", lambda v: f"{v:>4d} days"))
    print(get_agg_row("Loss Defense Days (-$3 Halt)", "loss_days", lambda v: f"{v:>4d} days"))
    print("=" * 105)
    
    print("\n📊 TRADE EXIT REASON BREAKDOWN ACROSS 6 MONTHS:")
    for s in strategies:
        print(f"\n  • {strat_labels[s]}:")
        for r, cnt in sorted(agg[s]["reasons"].items(), key=lambda x: -x[1]):
            print(f"      - {r:<15}: {cnt:>4d} trades ({cnt/agg[s]['trades']*100:>5.1f}%)")
            
    print(f"\n⚡ Total Execution Time: {time.time() - t_global:.1f} seconds")
