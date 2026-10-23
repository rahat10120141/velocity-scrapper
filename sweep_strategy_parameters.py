"""
VELOCITY SCALPER: Parameter Sweep & Strategy Optimizer for Confirmed 1H Bars
Evaluates across:
  Dataset A: October 3-23, 2026 Live Recorded Ticks (1.22M ticks)
  Dataset B: Full 2026 Year-to-Date Historical Bars (Jan 1 - Oct 23, 2026 - 10 months)
"""
import glob
import os
import json
import numpy as np
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

# Load 1h klines
klines_1h = {s: pd.read_csv(f"data/klines/{s}_1h_2026.csv", index_col=0, parse_dates=True) for s in SYMBOLS}

# Load October ticks
print("Loading October ticks...")
tick_data_by_sym = {}
for s in SYMBOLS:
    files = sorted(glob.glob(f"data/ticks/{s}_2026-10-*.csv"))
    dfs = [pd.read_csv(f, usecols=["timestamp_utc", "price"]) for f in files]
    m = pd.concat(dfs, ignore_index=True)
    m["dt"] = pd.to_datetime(m["timestamp_utc"], utc=True)
    m.dropna(subset=["dt", "price"], inplace=True)
    m.drop_duplicates(subset=["dt"], inplace=True)
    m.sort_values("dt", inplace=True)
    tick_data_by_sym[s] = m

all_times_utc = sorted(list(set.union(*[set(df["dt"]) for df in tick_data_by_sym.values()])))
price_lookups = {s: dict(zip(tick_data_by_sym[s]["dt"], tick_data_by_sym[s]["price"].astype(float))) for s in SYMBOLS}

def prepare_indicators(df, fast_p=9, slow_p=21, trend_p=200, atr_p=14, rsi_p=14):
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]
    
    df["ema_fast"] = c.ewm(span=fast_p, adjust=False).mean()
    df["ema_slow"] = c.ewm(span=slow_p, adjust=False).mean()
    df["ema_trend"] = c.ewm(span=trend_p, adjust=False).mean()
    
    c_prev = c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - c_prev).abs(), (l - c_prev).abs()))
    df["atr"] = tr.rolling(atr_p).mean()
    
    delta = c.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(rsi_p).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(rsi_p).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))
    
    # ADX(14)
    up_move = h - h.shift(1)
    down_move = l.shift(1) - l
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_smooth = pd.Series(tr).ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / (tr_smooth + 1e-9))
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / (tr_smooth + 1e-9))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
    df["adx"] = dx.ewm(alpha=1/14, adjust=False).mean()
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    
    # Volume SMA
    df["vol_sma"] = v.rolling(20).mean()
    df["vol_ratio"] = v / (df["vol_sma"] + 1e-9)
    return df

# Evaluate strategy on October Live Ticks
def simulate_october_ticks(ind_dfs, sl_mult=1.8, rr=2.2, be_mode="ladder", use_adx=False, adx_min=20, rsi_bounds=(45, 68), max_slots=2):
    balance = 100.0
    peak = 100.0
    max_dd = 0.0
    fee_rate = 0.0004
    margin = 25.0
    leverage = 5
    notional = margin * leverage # $125
    
    # Precompute signals on closed 1h candles
    signals_by_sym = {}
    for s in SYMBOLS:
        df = ind_dfs[s]
        c = df["close"]
        fast = df["ema_fast"]
        slow = df["ema_slow"]
        trend = df["ema_trend"]
        rsi = df["rsi"]
        adx = df["adx"]
        p_di = df["plus_di"]
        m_di = df["minus_di"]
        
        cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        
        buy = (c > trend) & cross_up & (rsi > rsi_bounds[0]) & (rsi < rsi_bounds[1])
        sell = (c < trend) & cross_down & (rsi < (100 - rsi_bounds[0])) & (rsi > (100 - rsi_bounds[1]))
        
        if use_adx:
            buy = buy & (adx >= adx_min) & (p_di > m_di)
            sell = sell & (adx >= adx_min) & (m_di > p_di)
            
        sig = pd.Series(0, index=df.index)
        sig[buy] = 1
        sig[sell] = -1
        signals_by_sym[s] = sig
        
    active_positions = []
    closed_trades = []
    prev_hour_ts = None
    
    for t in all_times_utc:
        curr_hour_ts = t.replace(minute=0, second=0, microsecond=0)
        
        # 1. Manage active positions on tick
        surviving = []
        for pos in active_positions:
            s = pos["symbol"]
            curr_p = price_lookups[s].get(t)
            if curr_p is None:
                surviving.append(pos)
                continue
                
            d = pos["direction"]
            en_p = pos["entry_price"]
            sl_dist = pos["sl_dist"]
            q = pos["quantity"]
            closed = False
            exit_p = curr_p
            reason = ""
            
            if d == 1:
                if curr_p > pos["peak_p"]:
                    pos["peak_p"] = curr_p
                gain_r = (curr_p - en_p) / sl_dist if sl_dist > 0 else 0
                gain_pct = (curr_p - en_p) / en_p
                
                if be_mode == "ladder":
                    if gain_r >= 1.2 and pos["ladder_step"] < 1:
                        pos["sl_price"] = en_p + (0.5 * sl_dist)
                        pos["ladder_step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["ladder_step"] < 2:
                        pos["sl_price"] = en_p + (1.2 * sl_dist)
                        pos["ladder_step"] = 2
                elif be_mode == "trailing":
                    if gain_pct >= 0.0100:
                        pos["be_locked"] = True
                        tr_target = pos["peak_p"] * (1.0 - 0.0040)
                        if tr_target > pos["sl_price"]:
                            pos["sl_price"] = tr_target
                elif be_mode == "runner":
                    if gain_r >= 1.4 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * 1.0018
                        pos["be_locked"] = True
                        
                if curr_p >= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif curr_p <= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    reason = "BREAK_EVEN" if pos["be_locked"] and exit_p >= en_p else "STOP_LOSS"
                    closed = True
                    
                if closed:
                    gross = (exit_p - en_p) * q
                    fees = (en_p * q + exit_p * q) * fee_rate
                    net = gross - fees
            else:
                if curr_p < pos["peak_p"]:
                    pos["peak_p"] = curr_p
                gain_r = (en_p - curr_p) / sl_dist if sl_dist > 0 else 0
                gain_pct = (en_p - curr_p) / en_p
                
                if be_mode == "ladder":
                    if gain_r >= 1.2 and pos["ladder_step"] < 1:
                        pos["sl_price"] = en_p - (0.5 * sl_dist)
                        pos["ladder_step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["ladder_step"] < 2:
                        pos["sl_price"] = en_p - (1.2 * sl_dist)
                        pos["ladder_step"] = 2
                elif be_mode == "trailing":
                    if gain_pct >= 0.0100:
                        pos["be_locked"] = True
                        tr_target = pos["peak_p"] * (1.0 + 0.0040)
                        if tr_target < pos["sl_price"]:
                            pos["sl_price"] = tr_target
                elif be_mode == "runner":
                    if gain_r >= 1.4 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                        
                if curr_p <= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif curr_p >= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    reason = "BREAK_EVEN" if pos["be_locked"] and exit_p <= en_p else "STOP_LOSS"
                    closed = True
                    
                if closed:
                    gross = (en_p - exit_p) * q
                    fees = (en_p * q + exit_p * q) * fee_rate
                    net = gross - fees
                    
            if closed:
                balance += net
                if balance > peak:
                    peak = balance
                dd = peak - balance
                if dd > max_dd:
                    max_dd = dd
                closed_trades.append({"net": net, "reason": reason})
            else:
                surviving.append(pos)
                
        active_positions = surviving
        
        # 2. Check for new entries on 1h bar close
        if curr_hour_ts != prev_hour_ts:
            prev_hour_ts = curr_hour_ts
            eval_time = curr_hour_ts - pd.Timedelta(hours=1)
            
            if len(active_positions) < max_slots:
                open_syms = {p["symbol"] for p in active_positions}
                for s in SYMBOLS:
                    if s in open_syms:
                        continue
                    if len(active_positions) >= max_slots:
                        break
                        
                    sig_ser = signals_by_sym[s]
                    df_s = ind_dfs[s]
                    
                    if eval_time in sig_ser.index:
                        sig = sig_ser.loc[eval_time]
                        if sig != 0:
                            curr_tick_p = price_lookups[s].get(t)
                            if curr_tick_p is None:
                                continue
                            atr = df_s.loc[eval_time, "atr"]
                            if pd.isna(atr) or atr <= 0:
                                continue
                            sl_dist = sl_mult * atr
                            tp_dist = rr * sl_dist
                            qty = notional / curr_tick_p
                            
                            sl_price = curr_tick_p - sl_dist if sig == 1 else curr_tick_p + sl_dist
                            tp_price = curr_tick_p + tp_dist if sig == 1 else curr_tick_p - tp_dist
                            
                            new_pos = {
                                "symbol": s,
                                "direction": sig,
                                "entry_price": curr_tick_p,
                                "quantity": qty,
                                "sl_dist": sl_dist,
                                "sl_price": sl_price,
                                "tp_price": tp_price,
                                "be_locked": False,
                                "ladder_step": 0,
                                "peak_p": curr_tick_p
                            }
                            active_positions.append(new_pos)
                            open_syms.add(s)

    tot = len(closed_trades)
    if tot == 0:
        return {"net": 0.0, "trades": 0, "wr": 0.0, "pf": 0.0, "dd": 0.0}
    wins = [t for t in closed_trades if t["net"] > 0]
    losses = [t for t in closed_trades if t["net"] < 0]
    win_usd = sum(t["net"] for t in wins)
    loss_usd = abs(sum(t["net"] for t in losses))
    pf = round(win_usd / loss_usd, 2) if loss_usd > 0 else 999.0
    return {
        "net": round(balance - 100.0, 2),
        "trades": tot,
        "wr": round(len(wins) / tot * 100, 1),
        "pf": pf,
        "dd": round(max_dd, 2)
    }

# Also evaluate on Full 2026 Historical 1H Bars (Jan 1 - Oct 23, 2026)
def simulate_full_2026(ind_dfs, sl_mult=1.8, rr=2.2, be_mode="ladder", use_adx=False, adx_min=20, rsi_bounds=(45, 68), max_slots=2):
    balance = 100.0
    peak = 100.0
    max_dd = 0.0
    fee_rate = 0.0004
    margin = 25.0
    leverage = 5
    notional = margin * leverage
    
    sim_start = pd.Timestamp("2026-01-01 00:00:00+00:00")
    all_dates = sorted(list(set.union(*[set(df.index) for df in ind_dfs.values()])))
    sim_dates = [d for d in all_dates if d >= sim_start]
    
    signals_by_sym = {}
    for s in SYMBOLS:
        df = ind_dfs[s]
        c = df["close"]
        fast = df["ema_fast"]
        slow = df["ema_slow"]
        trend = df["ema_trend"]
        rsi = df["rsi"]
        adx = df["adx"]
        p_di = df["plus_di"]
        m_di = df["minus_di"]
        
        cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        
        buy = (c > trend) & cross_up & (rsi > rsi_bounds[0]) & (rsi < rsi_bounds[1])
        sell = (c < trend) & cross_down & (rsi < (100 - rsi_bounds[0])) & (rsi > (100 - rsi_bounds[1]))
        
        if use_adx:
            buy = buy & (adx >= adx_min) & (p_di > m_di)
            sell = sell & (adx >= adx_min) & (m_di > p_di)
            
        sig = pd.Series(0, index=df.index)
        sig[buy] = 1
        sig[sell] = -1
        signals_by_sym[s] = sig
        
    active_positions = []
    closed_trades = []
    
    for t in sim_dates:
        # 1. Manage active positions on 1H bar (high/low)
        surviving = []
        for pos in active_positions:
            s = pos["symbol"]
            df_s = ind_dfs[s]
            if t not in df_s.index:
                surviving.append(pos)
                continue
                
            row = df_s.loc[t]
            curr_c = row["close"]
            curr_h = row["high"]
            curr_l = row["low"]
            
            d = pos["direction"]
            en_p = pos["entry_price"]
            sl_dist = pos["sl_dist"]
            q = pos["quantity"]
            closed = False
            exit_p = curr_c
            reason = ""
            
            if d == 1:
                gain_r = (curr_h - en_p) / sl_dist if sl_dist > 0 else 0
                if be_mode == "ladder":
                    if gain_r >= 1.2 and pos["ladder_step"] < 1:
                        pos["sl_price"] = en_p + (0.5 * sl_dist)
                        pos["ladder_step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["ladder_step"] < 2:
                        pos["sl_price"] = en_p + (1.2 * sl_dist)
                        pos["ladder_step"] = 2
                elif be_mode == "runner":
                    if gain_r >= 1.4 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * 1.0018
                        pos["be_locked"] = True
                        
                if curr_h >= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif curr_l <= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    reason = "BREAK_EVEN" if pos["be_locked"] and exit_p >= en_p else "STOP_LOSS"
                    closed = True
                    
                if closed:
                    gross = (exit_p - en_p) * q
                    fees = (en_p * q + exit_p * q) * fee_rate
                    net = gross - fees
            else:
                gain_r = (en_p - curr_l) / sl_dist if sl_dist > 0 else 0
                if be_mode == "ladder":
                    if gain_r >= 1.2 and pos["ladder_step"] < 1:
                        pos["sl_price"] = en_p - (0.5 * sl_dist)
                        pos["ladder_step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["ladder_step"] < 2:
                        pos["sl_price"] = en_p - (1.2 * sl_dist)
                        pos["ladder_step"] = 2
                elif be_mode == "runner":
                    if gain_r >= 1.4 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                        
                if curr_l <= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif curr_h >= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    reason = "BREAK_EVEN" if pos["be_locked"] and exit_p <= en_p else "STOP_LOSS"
                    closed = True
                    
                if closed:
                    gross = (en_p - exit_p) * q
                    fees = (en_p * q + exit_p * q) * fee_rate
                    net = gross - fees
                    
            if closed:
                balance += net
                if balance > peak:
                    peak = balance
                dd = peak - balance
                if dd > max_dd:
                    max_dd = dd
                closed_trades.append({"net": net, "reason": reason})
            else:
                surviving.append(pos)
                
        active_positions = surviving
        
        # 2. Check for new entries
        if len(active_positions) < max_slots:
            open_syms = {p["symbol"] for p in active_positions}
            for s in SYMBOLS:
                if s in open_syms:
                    continue
                if len(active_positions) >= max_slots:
                    break
                    
                sig_ser = signals_by_sym[s]
                df_s = ind_dfs[s]
                if t in sig_ser.index:
                    sig = sig_ser.loc[t]
                    if sig != 0:
                        c_p = df_s.loc[t, "close"]
                        atr = df_s.loc[t, "atr"]
                        if pd.isna(atr) or atr <= 0:
                            continue
                        sl_dist = sl_mult * atr
                        tp_dist = rr * sl_dist
                        qty = notional / c_p
                        
                        sl_price = c_p - sl_dist if sig == 1 else c_p + sl_dist
                        tp_price = c_p + tp_dist if sig == 1 else c_p - tp_dist
                        
                        new_pos = {
                            "symbol": s,
                            "direction": sig,
                            "entry_price": c_p,
                            "quantity": qty,
                            "sl_dist": sl_dist,
                            "sl_price": sl_price,
                            "tp_price": tp_price,
                            "be_locked": False,
                            "ladder_step": 0
                        }
                        active_positions.append(new_pos)
                        open_syms.add(s)

    tot = len(closed_trades)
    if tot == 0:
        return {"net": 0.0, "trades": 0, "wr": 0.0, "pf": 0.0, "dd": 0.0}
    wins = [t for t in closed_trades if t["net"] > 0]
    losses = [t for t in closed_trades if t["net"] < 0]
    win_usd = sum(t["net"] for t in wins)
    loss_usd = abs(sum(t["net"] for t in losses))
    pf = round(win_usd / loss_usd, 2) if loss_usd > 0 else 999.0
    return {
        "net": round(balance - 100.0, 2),
        "trades": tot,
        "wr": round(len(wins) / tot * 100, 1),
        "pf": pf,
        "dd": round(max_dd, 2)
    }

# PARAMETER GRID SWEEP
print("\n--- Running Multi-Dimensional Strategy & Parameter Sweep ---")
parameter_configs = [
    # Baseline variants
    {"id": "Base_1.8ATR_2.2R_Runner", "sl": 1.8, "rr": 2.2, "be": "runner", "adx": False, "adx_min": 0, "rsi": (45, 68), "slots": 2},
    {"id": "Base_1.8ATR_2.2R_Ladder", "sl": 1.8, "rr": 2.2, "be": "ladder", "adx": False, "adx_min": 0, "rsi": (45, 68), "slots": 2},
    {"id": "Base_1.8ATR_2.2R_3Slots", "sl": 1.8, "rr": 2.2, "be": "runner", "adx": False, "adx_min": 0, "rsi": (45, 68), "slots": 3},
    
    # ATR & RR Optimizations
    {"id": "Opt_1.5ATR_2.5R_Ladder", "sl": 1.5, "rr": 2.5, "be": "ladder", "adx": False, "adx_min": 0, "rsi": (45, 68), "slots": 2},
    {"id": "Opt_1.5ATR_2.5R_Runner", "sl": 1.5, "rr": 2.5, "be": "runner", "adx": False, "adx_min": 0, "rsi": (45, 68), "slots": 2},
    {"id": "Opt_1.6ATR_2.4R_Ladder", "sl": 1.6, "rr": 2.4, "be": "ladder", "adx": False, "adx_min": 0, "rsi": (45, 68), "slots": 2},
    {"id": "Opt_2.0ATR_2.5R_Ladder", "sl": 2.0, "rr": 2.5, "be": "ladder", "adx": False, "adx_min": 0, "rsi": (45, 68), "slots": 2},
    
    # ADX Regime Filter Variants
    {"id": "ADX18_1.5ATR_2.5R_Ladder", "sl": 1.5, "rr": 2.5, "be": "ladder", "adx": True, "adx_min": 18, "rsi": (45, 68), "slots": 2},
    {"id": "ADX20_1.5ATR_2.5R_Ladder", "sl": 1.5, "rr": 2.5, "be": "ladder", "adx": True, "adx_min": 20, "rsi": (45, 68), "slots": 2},
    {"id": "ADX22_1.5ATR_2.5R_Ladder", "sl": 1.5, "rr": 2.5, "be": "ladder", "adx": True, "adx_min": 22, "rsi": (45, 68), "slots": 2},
    {"id": "ADX20_1.8ATR_2.2R_Runner", "sl": 1.8, "rr": 2.2, "be": "runner", "adx": True, "adx_min": 20, "rsi": (45, 68), "slots": 2},
    
    # RSI Momentum Tweaks
    {"id": "RSI_48_65_1.6ATR_2.5R_Ladder", "sl": 1.6, "rr": 2.5, "be": "ladder", "adx": False, "adx_min": 0, "rsi": (48, 65), "slots": 2},
    {"id": "RSI_48_65_1.5ATR_2.5R_3Slots", "sl": 1.5, "rr": 2.5, "be": "ladder", "adx": False, "adx_min": 0, "rsi": (48, 65), "slots": 3},
]

# Compute indicators for default 9/21/200
ind_dfs = {s: prepare_indicators(klines_1h[s].copy(), 9, 21, 200) for s in SYMBOLS}

comparison_table = []
for p in parameter_configs:
    oct_res = simulate_october_ticks(
        ind_dfs,
        sl_mult=p["sl"],
        rr=p["rr"],
        be_mode=p["be"],
        use_adx=p["adx"],
        adx_min=p["adx_min"],
        rsi_bounds=p["rsi"],
        max_slots=p["slots"]
    )
    ytd_res = simulate_full_2026(
        ind_dfs,
        sl_mult=p["sl"],
        rr=p["rr"],
        be_mode=p["be"],
        use_adx=p["adx"],
        adx_min=p["adx_min"],
        rsi_bounds=p["rsi"],
        max_slots=p["slots"]
    )
    
    row = {
        "Config": p["id"],
        "Oct_Net": oct_res["net"],
        "Oct_WR": oct_res["wr"],
        "Oct_Trades": oct_res["trades"],
        "Oct_PF": oct_res["pf"],
        "Oct_DD": oct_res["dd"],
        "YTD_Net": ytd_res["net"],
        "YTD_WR": ytd_res["wr"],
        "YTD_Trades": ytd_res["trades"],
        "YTD_PF": ytd_res["pf"],
        "YTD_DD": ytd_res["dd"],
    }
    comparison_table.append(row)
    print(f"[{p['id']}] Oct: ${oct_res['net']:+.2f} (WR {oct_res['wr']}%, {oct_res['trades']} tr, DD ${oct_res['dd']}) | YTD 2026: ${ytd_res['net']:+.2f} (WR {ytd_res['wr']}%, {ytd_res['trades']} tr, DD ${ytd_res['dd']})")

print("\n\n" + "=" * 110)
print("             COMPREHENSIVE DUAL-PERIOD PERFORMANCE RANKING TABLE")
print("=" * 110)
print(f"{'Configuration':<30} | {'Oct Net':<9} | {'Oct WR':<7} | {'Oct DD':<8} | {'YTD 2026 Net':<13} | {'YTD WR':<8} | {'YTD DD':<8} | {'YTD PF':<6}")
print("-" * 110)
for r in sorted(comparison_table, key=lambda x: (x["Oct_Net"] + x["YTD_Net"]), reverse=True):
    print(f"{r['Config']:<30} | ${r['Oct_Net']:<+8.2f} | {r['Oct_WR']:<6.1f}% | ${r['Oct_DD']:<7.2f} | ${r['YTD_Net']:<+12.2f} | {r['YTD_WR']:<7.1f}% | ${r['YTD_DD']:<7.2f} | {r['YTD_PF']:<6}")
print("=" * 110)

with open("parameter_sweep_results.json", "w") as f:
    json.dump(comparison_table, f, indent=2)
