import sys
sys.path.insert(0, "/home/rahat/Documents/claude/aggresive")
import time
from backtest_6month_trailing_comparison import stream_ticks, fetch_1h_klines, prepare_signals, simulate_portfolio, SYMBOLS, MONTHS, TICK_STORE
import numpy as np
import datetime
from concurrent.futures import ProcessPoolExecutor

def evaluate_month_hybrid(month):
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
                sl_dist = open_trade["sl_dist"]
                closed = False
                exit_p = price
                reason = ""
                
                if d == 1:
                    if price > open_trade["highest_p"]:
                        open_trade["highest_p"] = price
                    highest_p = open_trade["highest_p"]
                    gain_pct = (highest_p - entry_p) / entry_p
                    gain_r = (highest_p - entry_p) / sl_dist if sl_dist > 0 else 0
                    
                    # 1. Early Fee Shield: at +0.25% gain, lock SL to +0.10% (covers fees + profit)
                    if not open_trade["shield_locked"] and gain_pct >= 0.0025:
                        be_sl = entry_p * 1.0010
                        if be_sl > open_trade["sl_price"]:
                            open_trade["sl_price"] = be_sl
                        open_trade["shield_locked"] = True
                        
                    # 2. Step Lock at +1.0R: lock SL at +0.40R
                    if not open_trade["r1_locked"] and gain_r >= 1.0:
                        r1_sl = entry_p + (0.40 * sl_dist)
                        if r1_sl > open_trade["sl_price"]:
                            open_trade["sl_price"] = r1_sl
                        open_trade["r1_locked"] = True
                        
                    # 3. Step Lock at +1.5R: lock SL at +1.0R
                    if not open_trade["r15_locked"] and gain_r >= 1.5:
                        r15_sl = entry_p + (1.00 * sl_dist)
                        if r15_sl > open_trade["sl_price"]:
                            open_trade["sl_price"] = r15_sl
                        open_trade["r15_locked"] = True
                        
                    # 4. Check TP and SL
                    if price >= open_trade["tp_price"]:
                        closed = True
                        exit_p = open_trade["tp_price"]
                        reason = "TP_HIT"
                    elif price <= open_trade["sl_price"]:
                        closed = True
                        exit_p = open_trade["sl_price"]
                        if open_trade["r15_locked"]:
                            reason = "PROFIT_LOCK_1.5R"
                        elif open_trade["r1_locked"]:
                            reason = "PROFIT_LOCK_1.0R"
                        elif open_trade["shield_locked"]:
                            reason = "FEE_SHIELD_EXIT"
                        else:
                            reason = "SL_HIT"
                            
                elif d == -1:
                    if price < open_trade["lowest_p"]:
                        open_trade["lowest_p"] = price
                    lowest_p = open_trade["lowest_p"]
                    gain_pct = (entry_p - lowest_p) / entry_p
                    gain_r = (entry_p - lowest_p) / sl_dist if sl_dist > 0 else 0
                    
                    if not open_trade["shield_locked"] and gain_pct >= 0.0025:
                        be_sl = entry_p * (1.0 - 0.0010)
                        if be_sl < open_trade["sl_price"]:
                            open_trade["sl_price"] = be_sl
                        open_trade["shield_locked"] = True
                        
                    if not open_trade["r1_locked"] and gain_r >= 1.0:
                        r1_sl = entry_p - (0.40 * sl_dist)
                        if r1_sl < open_trade["sl_price"]:
                            open_trade["sl_price"] = r1_sl
                        open_trade["r1_locked"] = True
                        
                    if not open_trade["r15_locked"] and gain_r >= 1.5:
                        r15_sl = entry_p - (1.00 * sl_dist)
                        if r15_sl < open_trade["sl_price"]:
                            open_trade["sl_price"] = r15_sl
                        open_trade["r15_locked"] = True
                        
                    if price <= open_trade["tp_price"]:
                        closed = True
                        exit_p = open_trade["tp_price"]
                        reason = "TP_HIT"
                    elif price >= open_trade["sl_price"]:
                        closed = True
                        exit_p = open_trade["sl_price"]
                        if open_trade["r15_locked"]:
                            reason = "PROFIT_LOCK_1.5R"
                        elif open_trade["r1_locked"]:
                            reason = "PROFIT_LOCK_1.0R"
                        elif open_trade["shield_locked"]:
                            reason = "FEE_SHIELD_EXIT"
                        else:
                            reason = "SL_HIT"
                            
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
                    "atr": atr,
                    "sl_dist": sl_dist,
                    "highest_p": entry_p,
                    "lowest_p": entry_p,
                    "sl_price": entry_p - sl_dist if d == 1 else entry_p + sl_dist,
                    "tp_price": entry_p + tp_dist if d == 1 else entry_p - tp_dist,
                    "shield_locked": False,
                    "r1_locked": False,
                    "r15_locked": False,
                    "pos_size": pos_size
                }
                
    candidates.sort(key=lambda x: x["entry_ts_ms"])
    res = simulate_portfolio(candidates, max_concurrent=3)
    res["month"] = month
    return res

if __name__ == "__main__":
    t0 = time.time()
    print("Testing Hybrid Ladder Lock across 6 months...")
    with ProcessPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(evaluate_month_hybrid, MONTHS))
        
    print("\n" + "="*80)
    print(f"{'MONTH':<10} | {'TRADES':<8} | {'WIN RATE':<10} | {'NET PNL':<12} | {'PF':<6} | {'MAX DD':<8}")
    print("-" * 80)
    tot_pnl = sum(r["net_pnl"] for r in results)
    tot_trades = sum(r["trades"] for r in results)
    avg_wr = np.mean([r["win_rate"] for r in results])
    max_dd = max([r["max_dd"] for r in results])
    
    for r in results:
        print(f"{r['month']:<10} | {r['trades']:<8} | {r['win_rate']:<9.1f}% | ${r['net_pnl']:<+11.2f} | {r['pf']:<6.2f} | ${r['max_dd']:<7.2f}")
    print("-" * 80)
    print(f"{'TOTAL 6M':<10} | {tot_trades:<8} | {avg_wr:<9.1f}% | ${tot_pnl:<+11.2f} |        | ${max_dd:<7.2f}")
    print(f"Elapsed: {time.time()-t0:.1f}s")
