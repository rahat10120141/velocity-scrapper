"""
Test Today's (2026-10-03) 57,000 Live Recorded Ticks
Compares MAX_OPEN_POSITIONS = 2 vs MAX_OPEN_POSITIONS = 3
"""
import glob
import os
import pandas as pd
import numpy as np
import datetime

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT"]

def load_today_ticks():
    ticks_by_sym = {}
    all_timestamps = set()
    for s in SYMBOLS:
        fpath = f"data/ticks/{s}_2026-10-03.csv"
        if os.path.exists(fpath):
            df = pd.read_csv(fpath)
            df["time_dt"] = pd.to_datetime(df["timestamp_utc"])
            ticks_by_sym[s] = df.set_index("time_dt")
            all_timestamps.update(df["time_dt"].tolist())
    all_times = sorted(list(all_timestamps))
    return ticks_by_sym, all_times

def run_simulation(ticks_by_sym, all_times, max_slots=2, initial_balance=100.0, margin_per_trade=25.0, leverage=10, fee_rate=0.0004):
    balance = initial_balance
    peak_balance = initial_balance
    max_dd = 0.0
    active_positions = [] # list of open trades
    closed_trades = []
    
    # Track existing ETH SHORT position that carried over from 2026-10-02
    # In live bot, ETH SHORT was opened @ 2693.02 with 0.0464 ETH, margin 24.99, sl 2717.04, tp 2640.17, be_trigger 2668.9986
    eth_pos = {
        "symbol": "ETHUSDT",
        "direction": -1, # SHORT
        "entry_price": 2693.02,
        "entry_time": "2026-10-02 22:10:45",
        "quantity": 0.0464,
        "margin": 24.99,
        "sl_price": 2717.0414,
        "tp_price": 2640.1729,
        "be_trigger": 2668.9986,
        "be_locked": False
    }
    active_positions.append(eth_pos)
    
    for t in all_times:
        # 1. Update active positions with current tick price
        surviving_positions = []
        for pos in active_positions:
            sym = pos["symbol"]
            df = ticks_by_sym.get(sym)
            if df is None or t not in df.index:
                surviving_positions.append(pos)
                continue
            
            row = df.loc[t]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            curr_p = float(row["price"])
            d = pos["direction"]
            entry_p = pos["entry_price"]
            pos_size = pos["quantity"]
            closed = False
            exit_p = curr_p
            reason = ""
            
            if d == 1: # LONG
                if not pos["be_locked"] and curr_p >= pos["be_trigger"]:
                    pos["sl_price"] = round(entry_p * 1.0018, 4)
                    pos["be_locked"] = True
                if curr_p >= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif curr_p <= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    reason = "BREAK_EVEN" if pos["be_locked"] else "STOP_LOSS"
                    closed = True
                if closed:
                    gross = (exit_p - entry_p) * pos_size
                    fees = (entry_p * pos_size + exit_p * pos_size) * fee_rate
                    net = gross - fees
            elif d == -1: # SHORT
                if not pos["be_locked"] and curr_p <= pos["be_trigger"]:
                    pos["sl_price"] = round(entry_p * (1.0 - 0.0018), 4)
                    pos["be_locked"] = True
                if curr_p <= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif curr_p >= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    reason = "BREAK_EVEN" if pos["be_locked"] else "STOP_LOSS"
                    closed = True
                if closed:
                    gross = (entry_p - exit_p) * pos_size
                    fees = (entry_p * pos_size + exit_p * pos_size) * fee_rate
                    net = gross - fees
                    
            if closed:
                balance += net
                if balance > peak_balance:
                    peak_balance = balance
                dd = peak_balance - balance
                if dd > max_dd:
                    max_dd = dd
                closed_trades.append({
                    "symbol": sym,
                    "direction": "LONG" if d == 1 else "SHORT",
                    "entry_time": pos["entry_time"],
                    "exit_time": str(t),
                    "entry_price": entry_p,
                    "exit_price": exit_p,
                    "net_pnl": round(net, 2),
                    "gross_pnl": round(gross, 2),
                    "fees": round(fees, 2),
                    "reason": reason
                })
            else:
                surviving_positions.append(pos)
                
        active_positions = surviving_positions
        
        # 2. Check for new signals if slots available
        if len(active_positions) < max_slots:
            open_symbols = {p["symbol"] for p in active_positions}
            for sym in SYMBOLS:
                if sym in open_symbols:
                    continue
                if len(active_positions) >= max_slots:
                    break
                df = ticks_by_sym.get(sym)
                if df is None or t not in df.index:
                    continue
                row = df.loc[t]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                sig = int(row["signal"])
                if sig != 0:
                    curr_p = float(row["price"])
                    atr = float(row["atr"]) if pd.notna(row["atr"]) and row["atr"] > 0 else (curr_p * 0.005)
                    sl_dist = 1.0 * atr
                    tp_dist = 2.2 * sl_dist
                    pos_size = 2.50 / sl_dist
                    # cap notional to $250 ($25 margin * 10x)
                    if (curr_p * pos_size) > 250.0:
                        pos_size = 250.0 / curr_p
                    pos_size = round(pos_size, 4)
                    
                    new_pos = {
                        "symbol": sym,
                        "direction": sig,
                        "entry_price": curr_p,
                        "entry_time": str(t),
                        "quantity": pos_size,
                        "margin": round((curr_p * pos_size) / leverage, 2),
                        "sl_price": round(curr_p - sl_dist, 4) if sig == 1 else round(curr_p + sl_dist, 4),
                        "tp_price": round(curr_p + tp_dist, 4) if sig == 1 else round(curr_p - tp_dist, 4),
                        "be_trigger": round(curr_p + sl_dist, 4) if sig == 1 else round(curr_p - sl_dist, 4),
                        "be_locked": False
                    }
                    active_positions.append(new_pos)
                    open_symbols.add(sym)

    # Calculate unrealized on remaining active positions
    latest_t = all_times[-1]
    unrealized_total = 0.0
    for pos in active_positions:
        sym = pos["symbol"]
        df = ticks_by_sym.get(sym)
        if df is not None and latest_t in df.index:
            row = df.loc[latest_t]
            if isinstance(row, pd.DataFrame): row = row.iloc[0]
            curr_p = float(row["price"])
            d = pos["direction"]
            u = (curr_p - pos["entry_price"]) * pos["quantity"] if d == 1 else (pos["entry_price"] - curr_p) * pos["quantity"]
            unrealized_total += u
            pos["current_price"] = curr_p
            pos["unrealized_pnl"] = round(u, 2)
            
    return {
        "max_slots": max_slots,
        "final_balance": round(balance, 2),
        "realized_pnl": round(balance - initial_balance, 2),
        "unrealized_pnl": round(unrealized_total, 2),
        "total_equity": round(balance + unrealized_total, 2),
        "closed_trades_count": len(closed_trades),
        "closed_trades": closed_trades,
        "still_active_count": len(active_positions),
        "still_active": active_positions,
        "max_drawdown": round(max_dd, 2)
    }

if __name__ == "__main__":
    print("Loading today's tick datasets...")
    ticks, times = load_today_ticks()
    print(f"Loaded {len(times)} synchronized tick timepoints across {len(ticks)} pairs.\n")
    
    print("=" * 70)
    print("  SIMULATION 1: CURRENT LIVE SETUP (MAX 2 SLOTS)")
    print("=" * 70)
    res2 = run_simulation(ticks, times, max_slots=2)
    print(f"Closed Trades: {res2['closed_trades_count']}")
    for tr in res2['closed_trades']:
        print(f"  [{tr['entry_time']}] {tr['symbol']} {tr['direction']} -> Net: ${tr['net_pnl']:+.2f} ({tr['reason']})")
    print(f"Realized PnL: ${res2['realized_pnl']:+.2f} | Unrealized: ${res2['unrealized_pnl']:+.2f} | Total Equity: ${res2['total_equity']:.2f}")
    print(f"Active Positions at End ({res2['still_active_count']}): {[p['symbol'] for p in res2['still_active']]}\n")

    print("=" * 70)
    print("  SIMULATION 2: EXPANDED SETUP (MAX 3 SLOTS -> 1 SLOT ADDED)")
    print("=" * 70)
    res3 = run_simulation(ticks, times, max_slots=3)
    print(f"Closed Trades: {res3['closed_trades_count']}")
    for tr in res3['closed_trades']:
        print(f"  [{tr['entry_time']}] {tr['symbol']} {tr['direction']} -> Net: ${tr['net_pnl']:+.2f} ({tr['reason']})")
    print(f"Realized PnL: ${res3['realized_pnl']:+.2f} | Unrealized: ${res3['unrealized_pnl']:+.2f} | Total Equity: ${res3['total_equity']:.2f}")
    print(f"Active Positions at End ({res3['still_active_count']}): {[p['symbol'] for p in res3['still_active']]}")
