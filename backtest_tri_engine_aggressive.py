"""
VELOCITY SCALPER: Tri-Engine Aggressive High-Yield Multi-Year Audit
Evaluates 3 distinct specialized engines designed for $1 - $3+ daily profit on $100 capital:
  Engine 1: Runner (High-Conviction 1H Swing Momentum: 1.5 ATR SL, 2.2R TP, 1.0R BE)
  Engine 2: Ladder (Intraday Multi-Target Scalper: 1.2 ATR SL, 3-Stage Ladder Lock)
  Engine 3: Trailing (Supertrend Volatility Breakout Surfer: Dynamic Ratchet)

Evaluated across:
  Period 1: Full Year 2025 (Jan 1 - Dec 31, 2025 - 9,168 bars/coin)
  Period 2: Full Year 2026 YTD (Jan 1 - Oct 23, 2026 - 7,837 bars/coin)
  Period 3: October 2026 Live Recorded Ticks (1.22M 5s ticks)
Universe: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, LINKUSDT
Capital: $100.00 per engine | Margin: $30.00 | Leverage: 10x ($300 Notional per trade)
"""
import glob
import os
import json
import time
import numpy as np
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

# Load 2025 and 2026 klines
print("Loading 2025 and 2026 1H historical klines...")
klines_2025 = {s: pd.read_csv(f"data/klines/{s}_1h_2025.csv", index_col=0, parse_dates=True) for s in SYMBOLS}
klines_2026 = {s: pd.read_csv(f"data/klines/{s}_1h_2026.csv", index_col=0, parse_dates=True) for s in SYMBOLS}

# Combine into continuous 2025-2026 dataset
klines_full = {}
for s in SYMBOLS:
    combined = pd.concat([klines_2025[s], klines_2026[s]])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)
    klines_full[s] = combined
    print(f"  {s}: {len(combined):,} continuous 1H bars ({combined.index[0]} to {combined.index[-1]})")

# Load October live recorded ticks
print("Loading October live recorded ticks...")
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
print(f"October ticks indexed: {len(all_times_utc):,} steps.")

def compute_engine_indicators(df):
    df = df.copy()
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]
    
    # EMAs
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_21"] = c.ewm(span=21, adjust=False).mean()
    df["ema_50"] = c.ewm(span=50, adjust=False).mean()
    df["ema_200"] = c.ewm(span=200, adjust=False).mean()
    
    # ATR(14)
    c_prev = c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - c_prev).abs(), (l - c_prev).abs()))
    df["atr"] = tr.rolling(14).mean()
    
    # RSI(14)
    delta = c.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))
    
    # Volume SMA(20)
    df["vol_sma"] = v.rolling(20).mean()
    df["vol_ratio"] = v / (df["vol_sma"] + 1e-9)
    
    # Supertrend(10, 3.0)
    st_period = 10
    st_mult = 3.0
    st_atr = tr.rolling(st_period).mean()
    basic_upper = ((h + l) / 2) + (st_mult * st_atr)
    basic_lower = ((h + l) / 2) - (st_mult * st_atr)
    
    st_dir = np.zeros(len(df))
    final_upper = basic_upper.values.copy()
    final_lower = basic_lower.values.copy()
    close_vals = c.values
    
    for i in range(1, len(df)):
        if basic_lower.values[i] > final_lower[i-1] or close_vals[i-1] < final_lower[i-1]:
            final_lower[i] = basic_lower.values[i]
        else:
            final_lower[i] = final_lower[i-1]
            
        if basic_upper.values[i] < final_upper[i-1] or close_vals[i-1] > final_upper[i-1]:
            final_upper[i] = basic_upper.values[i]
        else:
            final_upper[i] = final_upper[i-1]
            
        if i == 1:
            st_dir[i] = 1 if close_vals[i] > final_upper[i] else -1
        else:
            prev_dir = st_dir[i-1]
            if prev_dir == 1 and close_vals[i] < final_lower[i]:
                st_dir[i] = -1
            elif prev_dir == -1 and close_vals[i] > final_upper[i]:
                st_dir[i] = 1
            else:
                st_dir[i] = prev_dir
                
    df["st_dir"] = st_dir
    return df

ind_full = {s: compute_engine_indicators(klines_full[s]) for s in SYMBOLS}

# SIMULATION ENGINES
def run_period_simulation(engine_type, start_date_str, end_date_str, max_slots=2, margin=30.0, lev=10):
    start_dt = pd.Timestamp(start_date_str + " 00:00:00+00:00")
    end_dt = pd.Timestamp(end_date_str + " 23:59:59+00:00")
    
    all_dates = sorted(list(set.union(*[set(df.index) for df in ind_full.values()])))
    sim_dates = [d for d in all_dates if d >= start_dt and d <= end_dt]
    
    # Generate signals per engine
    signals_dict = {}
    for s in SYMBOLS:
        df = ind_full[s]
        c = df["close"]
        h = df["high"]
        l = df["low"]
        fast = df["ema_9"]
        slow = df["ema_21"]
        trend = df["ema_200"]
        rsi = df["rsi"]
        vol_r = df["vol_ratio"]
        st = df["st_dir"]
        
        cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        
        if engine_type == "runner":
            # 1H Swing Momentum: 9/21 cross + 200 EMA + RSI
            buy = (c > trend) & cross_up & (rsi > 45) & (rsi < 68)
            sell = (c < trend) & cross_down & (rsi > 32) & (rsi < 55)
            sl_mult = 1.5
            rr_ratio = 2.2
            be_trigger_r = 1.0
            
        elif engine_type == "ladder":
            # Multi-Target Intraday: 9/21 cross with 50 EMA trend + RSI
            buy = (c > df["ema_50"]) & cross_up & (rsi > 46) & (rsi < 66)
            sell = (c < df["ema_50"]) & cross_down & (rsi > 34) & (rsi < 54)
            sl_mult = 1.2
            rr_ratio = 2.2
            be_trigger_r = 1.0
            
        elif engine_type == "trailing":
            # Supertrend Volatility Breakout
            st_flip_up = (st == 1) & (st.shift(1) == -1) & (vol_r >= 1.0)
            st_flip_down = (st == -1) & (st.shift(1) == 1) & (vol_r >= 1.0)
            buy = st_flip_up
            sell = st_flip_down
            sl_mult = 1.6
            rr_ratio = 2.5
            be_trigger_r = 1.2
            
        sig = pd.Series(0, index=df.index)
        sig[buy] = 1
        sig[sell] = -1
        signals_dict[s] = sig
        
    balance = 100.0
    peak = 100.0
    max_dd = 0.0
    fee_rate = 0.0004
    notional = margin * lev # $300 notional
    
    active_positions = []
    closed_trades = []
    daily_pnl = {}
    
    for t in sim_dates:
        date_str = str(t)[:10]
        daily_pnl.setdefault(date_str, 0.0)
        
        # 1. Manage active positions on 1H bar
        surviving = []
        for pos in active_positions:
            s = pos["symbol"]
            df_s = ind_full[s]
            if t not in df_s.index:
                surviving.append(pos)
                continue
            row = df_s.loc[t]
            curr_c, curr_h, curr_l = row["close"], row["high"], row["low"]
            d = pos["direction"]
            en_p = pos["entry_price"]
            sl_dist = pos["sl_dist"]
            q = pos["quantity"]
            closed = False
            exit_p = curr_c
            reason = ""
            
            if d == 1:
                if curr_h > pos["peak_p"]:
                    pos["peak_p"] = curr_h
                gain_r = (curr_h - en_p) / sl_dist if sl_dist > 0 else 0
                gain_pct = (curr_h - en_p) / en_p
                
                if engine_type == "runner":
                    if gain_r >= 1.0 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * 1.0018
                        pos["be_locked"] = True
                elif engine_type == "ladder":
                    if gain_r >= 1.0 and pos["step"] < 1:
                        pos["sl_price"] = en_p + (0.5 * sl_dist)
                        pos["step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.6 and pos["step"] < 2:
                        pos["sl_price"] = en_p + (1.1 * sl_dist)
                        pos["step"] = 2
                elif engine_type == "trailing":
                    if gain_r >= 1.2 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * 1.0018
                        pos["be_locked"] = True
                    if gain_r >= 1.5:
                        trail_p = pos["peak_p"] - (0.6 * sl_dist)
                        if trail_p > pos["sl_price"]:
                            pos["sl_price"] = trail_p
                            
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
                if curr_l < pos["peak_p"]:
                    pos["peak_p"] = curr_l
                gain_r = (en_p - curr_l) / sl_dist if sl_dist > 0 else 0
                gain_pct = (en_p - curr_l) / en_p
                
                if engine_type == "runner":
                    if gain_r >= 1.0 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                elif engine_type == "ladder":
                    if gain_r >= 1.0 and pos["step"] < 1:
                        pos["sl_price"] = en_p - (0.5 * sl_dist)
                        pos["step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.6 and pos["step"] < 2:
                        pos["sl_price"] = en_p - (1.1 * sl_dist)
                        pos["step"] = 2
                elif engine_type == "trailing":
                    if gain_r >= 1.2 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                    if gain_r >= 1.5:
                        trail_p = pos["peak_p"] + (0.6 * sl_dist)
                        if trail_p < pos["sl_price"]:
                            pos["sl_price"] = trail_p
                            
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
                daily_pnl[date_str] += net
                if balance > peak:
                    peak = balance
                dd = peak - balance
                if dd > max_dd:
                    max_dd = dd
                closed_trades.append({
                    "symbol": s,
                    "net": net,
                    "reason": reason,
                    "date": date_str
                })
            else:
                surviving.append(pos)
                
        active_positions = surviving
        
        # 2. Check for new entries on confirmed bar close
        if len(active_positions) < max_slots:
            open_s = {p["symbol"] for p in active_positions}
            for s in SYMBOLS:
                if s in open_s or len(active_positions) >= max_slots:
                    continue
                sig_ser = signals_dict[s]
                df_s = ind_full[s]
                if t in sig_ser.index and sig_ser.loc[t] != 0:
                    c_p = df_s.loc[t, "close"]
                    atr = df_s.loc[t, "atr"]
                    if pd.isna(atr) or atr <= 0:
                        continue
                    sl_dist = sl_mult * atr
                    tp_dist = rr_ratio * sl_dist
                    qty = notional / c_p
                    sig = sig_ser.loc[t]
                    sl_p = c_p - sl_dist if sig == 1 else c_p + sl_dist
                    tp_p = c_p + tp_dist if sig == 1 else c_p - tp_dist
                    
                    active_positions.append({
                        "symbol": s,
                        "direction": sig,
                        "entry_price": c_p,
                        "quantity": qty,
                        "sl_dist": sl_dist,
                        "sl_price": sl_p,
                        "tp_price": tp_p,
                        "be_locked": False,
                        "step": 0,
                        "peak_p": c_p
                    })
                    open_s.add(s)

    tot_trades = len(closed_trades)
    if tot_trades == 0:
        return {"net": 0.0, "trades": 0, "wr": 0.0, "pf": 0.0, "dd": 0.0, "daily_avg": 0.0}
        
    wins = [t for t in closed_trades if t["net"] > 0]
    losses = [t for t in closed_trades if t["net"] < 0]
    win_usd = sum(t["net"] for t in wins)
    loss_usd = abs(sum(t["net"] for t in losses))
    pf = round(win_usd / loss_usd, 2) if loss_usd > 0 else 999.0
    net_pnl = round(balance - 100.0, 2)
    wr = round(len(wins) / tot_trades * 100, 1)
    
    # Calculate days in period
    num_days = (pd.Timestamp(end_date_str) - pd.Timestamp(start_date_str)).days + 1
    daily_avg = round(net_pnl / num_days, 2)
    
    return {
        "engine": engine_type,
        "net_pnl": net_pnl,
        "trades": tot_trades,
        "win_rate": wr,
        "profit_factor": pf,
        "max_dd": round(max_dd, 2),
        "daily_avg": daily_avg,
        "total_days": num_days
    }

# Also run simulation on October Live Recorded Ticks
def run_october_ticks_for_engine(engine_type, max_slots=2, margin=30.0, lev=10):
    notional = margin * lev
    fee_rate = 0.0004
    
    signals_dict = {}
    for s in SYMBOLS:
        df = ind_full[s]
        c = df["close"]
        fast = df["ema_9"]
        slow = df["ema_21"]
        trend = df["ema_200"]
        rsi = df["rsi"]
        vol_r = df["vol_ratio"]
        st = df["st_dir"]
        
        cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        
        if engine_type == "runner":
            buy = (c > trend) & cross_up & (rsi > 45) & (rsi < 68)
            sell = (c < trend) & cross_down & (rsi > 32) & (rsi < 55)
            sl_mult = 1.5
            rr_ratio = 2.2
        elif engine_type == "ladder":
            buy = (c > df["ema_50"]) & cross_up & (rsi > 46) & (rsi < 66)
            sell = (c < df["ema_50"]) & cross_down & (rsi > 34) & (rsi < 54)
            sl_mult = 1.2
            rr_ratio = 2.2
        elif engine_type == "trailing":
            st_flip_up = (st == 1) & (st.shift(1) == -1) & (vol_r >= 1.0)
            st_flip_down = (st == -1) & (st.shift(1) == 1) & (vol_r >= 1.0)
            buy = st_flip_up
            sell = st_flip_down
            sl_mult = 1.6
            rr_ratio = 2.5
            
        sig = pd.Series(0, index=df.index)
        sig[buy] = 1
        sig[sell] = -1
        signals_dict[s] = sig
        
    balance = 100.0
    peak = 100.0
    max_dd = 0.0
    active_positions = []
    closed_trades = []
    prev_h = None
    
    for t in all_times_utc:
        curr_h = t.replace(minute=0, second=0, microsecond=0)
        
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
                if engine_type == "runner":
                    if gain_r >= 1.0 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * 1.0018
                        pos["be_locked"] = True
                elif engine_type == "ladder":
                    if gain_r >= 1.0 and pos["step"] < 1:
                        pos["sl_price"] = en_p + (0.5 * sl_dist)
                        pos["step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.6 and pos["step"] < 2:
                        pos["sl_price"] = en_p + (1.1 * sl_dist)
                        pos["step"] = 2
                elif engine_type == "trailing":
                    if gain_r >= 1.2 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * 1.0018
                        pos["be_locked"] = True
                    if gain_r >= 1.5:
                        trail_p = pos["peak_p"] - (0.6 * sl_dist)
                        if trail_p > pos["sl_price"]:
                            pos["sl_price"] = trail_p
                            
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
                if engine_type == "runner":
                    if gain_r >= 1.0 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                elif engine_type == "ladder":
                    if gain_r >= 1.0 and pos["step"] < 1:
                        pos["sl_price"] = en_p - (0.5 * sl_dist)
                        pos["step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.6 and pos["step"] < 2:
                        pos["sl_price"] = en_p - (1.1 * sl_dist)
                        pos["step"] = 2
                elif engine_type == "trailing":
                    if gain_r >= 1.2 and not pos["be_locked"]:
                        pos["sl_price"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                    if gain_r >= 1.5:
                        trail_p = pos["peak_p"] + (0.6 * sl_dist)
                        if trail_p < pos["sl_price"]:
                            pos["sl_price"] = trail_p
                            
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
        
        # New entry
        if curr_h != prev_h:
            prev_h = curr_h
            eval_t = curr_h - pd.Timedelta(hours=1)
            if len(active_positions) < max_slots:
                open_s = {p["symbol"] for p in active_positions}
                for s in SYMBOLS:
                    if s in open_s or len(active_positions) >= max_slots:
                        continue
                    sig_ser = signals_dict[s]
                    df_s = ind_full[s]
                    if eval_t in sig_ser.index and sig_ser.loc[eval_t] != 0:
                        tick_p = price_lookups[s].get(t)
                        if tick_p is None:
                            continue
                        atr = df_s.loc[eval_t, "atr"]
                        if pd.isna(atr) or atr <= 0:
                            continue
                        sl_d = sl_mult * atr
                        tp_d = rr_ratio * sl_d
                        qty = notional / tick_p
                        sig = sig_ser.loc[eval_t]
                        sl_p = tick_p - sl_d if sig == 1 else tick_p + sl_d
                        tp_p = tick_p + tp_d if sig == 1 else tick_p - tp_d
                        active_positions.append({
                            "symbol": s,
                            "direction": sig,
                            "entry_price": tick_p,
                            "quantity": qty,
                            "sl_dist": sl_d,
                            "sl_price": sl_p,
                            "tp_price": tp_p,
                            "be_locked": False,
                            "step": 0,
                            "peak_p": tick_p
                        })
                        open_s.add(s)

    tot = len(closed_trades)
    if tot == 0:
        return {"net": 0.0, "trades": 0, "wr": 0.0, "pf": 0.0, "dd": 0.0}
    wins = [t for t in closed_trades if t["net"] > 0]
    losses = [t for t in closed_trades if t["net"] < 0]
    win_usd = sum(t["net"] for t in wins)
    loss_usd = abs(sum(t["net"] for t in losses))
    pf = round(win_usd / loss_usd, 2) if loss_usd > 0 else 999.0
    return {
        "engine": engine_type,
        "net_pnl": round(balance - 100.0, 2),
        "trades": tot,
        "win_rate": round(len(wins) / tot * 100, 1),
        "profit_factor": pf,
        "max_dd": round(max_dd, 2)
    }

print("\n" + "=" * 90)
print("             TRI-ENGINE MULTI-YEAR COMPREHENSIVE PERFORMANCE AUDIT")
print("=" * 90)

engines = ["runner", "ladder", "trailing"]
summary_report = []

for eng in engines:
    res_2025 = run_period_simulation(eng, "2025-01-01", "2025-12-31")
    res_2026 = run_period_simulation(eng, "2026-01-01", "2026-10-23")
    res_oct_ticks = run_october_ticks_for_engine(eng)
    
    summary_report.append({
        "engine": eng.upper(),
        "2025_net": res_2025["net_pnl"],
        "2025_wr": res_2025["win_rate"],
        "2025_trades": res_2025["trades"],
        "2025_pf": res_2025["profit_factor"],
        "2025_dd": res_2025["max_dd"],
        "2026_net": res_2026["net_pnl"],
        "2026_wr": res_2026["win_rate"],
        "2026_trades": res_2026["trades"],
        "2026_pf": res_2026["profit_factor"],
        "2026_dd": res_2026["max_dd"],
        "oct_net": res_oct_ticks["net_pnl"],
        "oct_wr": res_oct_ticks["win_rate"],
        "oct_trades": res_oct_ticks["trades"],
        "oct_dd": res_oct_ticks["max_dd"],
    })
    
    print(f"\nENGINE: {eng.upper()} ($100 Starting Capital, $30 Margin, 10x Lev)")
    print(f"  Year 2025 (Full): Net PnL: ${res_2025['net_pnl']:+.2f} ({res_2025['net_pnl']:.1f}%) | WR: {res_2025['win_rate']}% | Trades: {res_2025['trades']} | PF: {res_2025['profit_factor']} | Max DD: ${res_2025['max_dd']} | Daily Avg: ${res_2025['daily_avg']}/day")
    print(f"  Year 2026 (YTD) : Net PnL: ${res_2026['net_pnl']:+.2f} ({res_2026['net_pnl']:.1f}%) | WR: {res_2026['win_rate']}% | Trades: {res_2026['trades']} | PF: {res_2026['profit_factor']} | Max DD: ${res_2026['max_dd']} | Daily Avg: ${res_2026['daily_avg']}/day")
    print(f"  Oct 2026 Ticks  : Net PnL: ${res_oct_ticks['net_pnl']:+.2f} | WR: {res_oct_ticks['win_rate']}% | Trades: {res_oct_ticks['trades']} | Max DD: ${res_oct_ticks['max_dd']}")

print("\n\n" + "=" * 115)
print("                               TRI-ENGINE ECOSYSTEM SUMMARY TABLE")
print("=" * 115)
print(f"{'Engine':<12} | {'2025 Net PnL':<15} | {'2025 Win%':<10} | {'2026 Net PnL':<15} | {'2026 Win%':<10} | {'Oct Ticks Net':<14} | {'Total Profit':<14}")
print("-" * 115)
tot_combined = 0
for r in summary_report:
    tot_p = r["2025_net"] + r["2026_net"]
    tot_combined += tot_p
    print(f"{r['engine']:<12} | ${r['2025_net']:<+14.2f} | {r['2025_wr']:<9.1f}% | ${r['2026_net']:<+14.2f} | {r['2026_wr']:<9.1f}% | ${r['oct_net']:<+13.2f} | ${tot_p:<+13.2f}")
print("-" * 115)
print(f"{'COMBINED TRI-PORTFOLIO ($300 TOTAL BUDGET)':<68} | TOTAL GAIN: ${tot_combined:+.2f}")
print("=" * 115)

with open("tri_engine_audit_results.json", "w") as f:
    json.dump(summary_report, f, indent=2)
