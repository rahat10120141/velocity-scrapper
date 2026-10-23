"""
VELOCITY SCALPER: Engineering the Champion Strategy
Takes the proven Runner baseline and optimizes:
  1. Candle confirmation: Strictly enter on CONFIRMED 1H bar close
  2. Multi-Timeframe (4H 50 EMA trend filter)
  3. Dynamic Take-Profit Target (2.0R vs 2.2R vs 2.5R vs 3.0R)
  4. Break-Even Trigger Timing (1.2R vs 1.4R vs 1.6R)
  5. Trailing Lock at extreme targets (>2.0R trail)
  6. Concurrency: 2 slots vs 3 slots
"""
import glob
import os
import json
import numpy as np
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

# Load 1h and 4h klines
klines_1h = {s: pd.read_csv(f"data/klines/{s}_1h_2026.csv", index_col=0, parse_dates=True) for s in SYMBOLS}
klines_4h = {s: pd.read_csv(f"data/klines/{s}_4h_2026.csv", index_col=0, parse_dates=True) for s in SYMBOLS}

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

def prepare_data(df_1h, df_4h):
    df = df_1h.copy()
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]
    
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_21"] = c.ewm(span=21, adjust=False).mean()
    df["ema_50"] = c.ewm(span=50, adjust=False).mean()
    df["ema_200"] = c.ewm(span=200, adjust=False).mean()
    
    c_prev = c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - c_prev).abs(), (l - c_prev).abs()))
    df["atr"] = tr.rolling(14).mean()
    
    delta = c.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))
    
    # 4H EMA 50
    df_4h_c = df_4h["close"]
    df_4h_ema50 = df_4h_c.ewm(span=50, adjust=False).mean()
    df["macro_4h"] = df_4h_ema50.reindex(df.index, method="ffill")
    df["macro_bull"] = df["close"] > df["macro_4h"]
    
    df["vol_sma"] = v.rolling(20).mean()
    df["vol_ratio"] = v / (df["vol_sma"] + 1e-9)
    return df

ind_dfs = {s: prepare_data(klines_1h[s], klines_4h[s]) for s in SYMBOLS}

def evaluate_config(cfg):
    # Strategy settings
    fast_p = cfg.get("fast", 9)
    slow_p = cfg.get("slow", 21)
    sl_mult = cfg.get("sl_mult", 1.8)
    rr = cfg.get("rr", 2.2)
    be_r = cfg.get("be_r", 1.4)
    use_4h = cfg.get("use_4h", False)
    use_vol = cfg.get("use_vol", False)
    max_slots = cfg.get("slots", 2)
    trailing_r = cfg.get("trailing_r", 0.0) # If > 0, trail after this R
    
    signals_by_sym = {}
    for s in SYMBOLS:
        df = ind_dfs[s]
        c = df["close"]
        fast = df["ema_9"]
        slow = df["ema_21"]
        trend = df["ema_200"]
        rsi = df["rsi"]
        macro_bull = df["macro_bull"]
        vol_r = df["vol_ratio"]
        
        cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        
        buy = (c > trend) & cross_up & (rsi > 45) & (rsi < 68)
        sell = (c < trend) & cross_down & (rsi > 32) & (rsi < 55)
        
        if use_4h:
            buy = buy & macro_bull
            sell = sell & (~macro_bull)
            
        if use_vol:
            buy = buy & (vol_r >= 0.9)
            sell = sell & (vol_r >= 0.9)
            
        sig = pd.Series(0, index=df.index)
        sig[buy] = 1
        sig[sell] = -1
        signals_by_sym[s] = sig

    # --- OCTOBER REPLAY ---
    balance_oct = 100.0
    peak_oct = 100.0
    max_dd_oct = 0.0
    fee_rate = 0.0004
    margin = 25.0
    lev = 5
    notional = margin * lev
    
    active_positions = []
    closed_oct = []
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
                if gain_r >= be_r and not pos["be_locked"]:
                    pos["sl_price"] = en_p * 1.0018
                    pos["be_locked"] = True
                if trailing_r > 0 and gain_r >= trailing_r:
                    trail_p = pos["peak_p"] - (0.5 * sl_dist)
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
                if gain_r >= be_r and not pos["be_locked"]:
                    pos["sl_price"] = en_p * (1.0 - 0.0018)
                    pos["be_locked"] = True
                if trailing_r > 0 and gain_r >= trailing_r:
                    trail_p = pos["peak_p"] + (0.5 * sl_dist)
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
                balance_oct += net
                if balance_oct > peak_oct:
                    peak_oct = balance_oct
                dd = peak_oct - balance_oct
                if dd > max_dd_oct:
                    max_dd_oct = dd
                closed_oct.append(net)
            else:
                surviving.append(pos)
                
        active_positions = surviving
        
        # New entry on 1H bar close
        if curr_h != prev_h:
            prev_h = curr_h
            eval_t = curr_h - pd.Timedelta(hours=1)
            if len(active_positions) < max_slots:
                open_s = {p["symbol"] for p in active_positions}
                for s in SYMBOLS:
                    if s in open_s or len(active_positions) >= max_slots:
                        continue
                    sig_ser = signals_by_sym[s]
                    df_s = ind_dfs[s]
                    if eval_t in sig_ser.index and sig_ser.loc[eval_t] != 0:
                        tick_p = price_lookups[s].get(t)
                        if tick_p is None:
                            continue
                        atr = df_s.loc[eval_t, "atr"]
                        if pd.isna(atr) or atr <= 0:
                            continue
                        sl_d = sl_mult * atr
                        tp_d = rr * sl_d
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
                            "peak_p": tick_p
                        })
                        open_s.add(s)

    # --- FULL 2026 REPLAY ---
    balance_ytd = 100.0
    peak_ytd = 100.0
    max_dd_ytd = 0.0
    sim_start = pd.Timestamp("2026-01-01 00:00:00+00:00")
    all_dates = sorted(list(set.union(*[set(df.index) for df in ind_dfs.values()])))
    sim_dates = [d for d in all_dates if d >= sim_start]
    
    active_ytd = []
    closed_ytd = []
    
    for t in sim_dates:
        surviving = []
        for pos in active_ytd:
            s = pos["symbol"]
            df_s = ind_dfs[s]
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
            
            if d == 1:
                if curr_h > pos["peak_p"]:
                    pos["peak_p"] = curr_h
                gain_r = (curr_h - en_p) / sl_dist if sl_dist > 0 else 0
                if gain_r >= be_r and not pos["be_locked"]:
                    pos["sl_price"] = en_p * 1.0018
                    pos["be_locked"] = True
                if trailing_r > 0 and gain_r >= trailing_r:
                    trail_p = pos["peak_p"] - (0.5 * sl_dist)
                    if trail_p > pos["sl_price"]:
                        pos["sl_price"] = trail_p
                        
                if curr_h >= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    closed = True
                elif curr_l <= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    closed = True
                    
                if closed:
                    gross = (exit_p - en_p) * q
                    fees = (en_p * q + exit_p * q) * fee_rate
                    net = gross - fees
            else:
                if curr_l < pos["peak_p"]:
                    pos["peak_p"] = curr_l
                gain_r = (en_p - curr_l) / sl_dist if sl_dist > 0 else 0
                if gain_r >= be_r and not pos["be_locked"]:
                    pos["sl_price"] = en_p * (1.0 - 0.0018)
                    pos["be_locked"] = True
                if trailing_r > 0 and gain_r >= trailing_r:
                    trail_p = pos["peak_p"] + (0.5 * sl_dist)
                    if trail_p < pos["sl_price"]:
                        pos["sl_price"] = trail_p
                        
                if curr_l <= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    closed = True
                elif curr_h >= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    closed = True
                    
                if closed:
                    gross = (en_p - exit_p) * q
                    fees = (en_p * q + exit_p * q) * fee_rate
                    net = gross - fees
                    
            if closed:
                balance_ytd += net
                if balance_ytd > peak_ytd:
                    peak_ytd = balance_ytd
                dd = peak_ytd - balance_ytd
                if dd > max_dd_ytd:
                    max_dd_ytd = dd
                closed_ytd.append(net)
            else:
                surviving.append(pos)
                
        active_ytd = surviving
        
        # New entry
        if len(active_ytd) < max_slots:
            open_s = {p["symbol"] for p in active_ytd}
            for s in SYMBOLS:
                if s in open_s or len(active_ytd) >= max_slots:
                    continue
                sig_ser = signals_by_sym[s]
                df_s = ind_dfs[s]
                if t in sig_ser.index and sig_ser.loc[t] != 0:
                    c_p = df_s.loc[t, "close"]
                    atr = df_s.loc[t, "atr"]
                    if pd.isna(atr) or atr <= 0:
                        continue
                    sl_d = sl_mult * atr
                    tp_d = rr * sl_d
                    qty = notional / c_p
                    sig = sig_ser.loc[t]
                    sl_p = c_p - sl_d if sig == 1 else c_p + sl_d
                    tp_p = c_p + tp_d if sig == 1 else c_p - tp_d
                    active_ytd.append({
                        "symbol": s,
                        "direction": sig,
                        "entry_price": c_p,
                        "quantity": qty,
                        "sl_dist": sl_d,
                        "sl_price": sl_p,
                        "tp_price": tp_p,
                        "be_locked": False,
                        "peak_p": c_p
                    })
                    open_s.add(s)

    oct_tot = len(closed_oct)
    oct_net = round(balance_oct - 100.0, 2)
    oct_wr = round(len([x for x in closed_oct if x > 0]) / oct_tot * 100, 1) if oct_tot > 0 else 0
    
    ytd_tot = len(closed_ytd)
    ytd_net = round(balance_ytd - 100.0, 2)
    ytd_wr = round(len([x for x in closed_ytd if x > 0]) / ytd_tot * 100, 1) if ytd_tot > 0 else 0
    ytd_wins = [x for x in closed_ytd if x > 0]
    ytd_losses = [abs(x) for x in closed_ytd if x < 0]
    ytd_pf = round(sum(ytd_wins) / sum(ytd_losses), 2) if sum(ytd_losses) > 0 else 999.0
    
    return {
        "name": cfg["name"],
        "oct_net": oct_net,
        "oct_wr": oct_wr,
        "oct_trades": oct_tot,
        "oct_dd": round(max_dd_oct, 2),
        "ytd_net": ytd_net,
        "ytd_wr": ytd_wr,
        "ytd_trades": ytd_tot,
        "ytd_pf": ytd_pf,
        "ytd_dd": round(max_dd_ytd, 2),
        "total_score": oct_net + ytd_net
    }

configs_to_test = [
    {"name": "Runner_1.8ATR_2.2R_BE1.4R_2Slots", "sl_mult": 1.8, "rr": 2.2, "be_r": 1.4, "slots": 2},
    {"name": "Runner_1.8ATR_2.2R_BE1.4R_3Slots", "sl_mult": 1.8, "rr": 2.2, "be_r": 1.4, "slots": 3},
    {"name": "Runner_1.8ATR_2.5R_BE1.4R_2Slots", "sl_mult": 1.8, "rr": 2.5, "be_r": 1.4, "slots": 2},
    {"name": "Runner_1.8ATR_2.5R_BE1.4R_3Slots", "sl_mult": 1.8, "rr": 2.5, "be_r": 1.4, "slots": 3},
    {"name": "Runner_1.8ATR_2.8R_BE1.4R_2Slots", "sl_mult": 1.8, "rr": 2.8, "be_r": 1.4, "slots": 2},
    {"name": "Runner_2.0ATR_2.5R_BE1.4R_2Slots", "sl_mult": 2.0, "rr": 2.5, "be_r": 1.4, "slots": 2},
    {"name": "Runner_1.8ATR_2.2R_BE1.2R_2Slots", "sl_mult": 1.8, "rr": 2.2, "be_r": 1.2, "slots": 2},
    {"name": "Runner_1.8ATR_2.2R_BE1.6R_2Slots", "sl_mult": 1.8, "rr": 2.2, "be_r": 1.6, "slots": 2},
    {"name": "Runner_1.8ATR_2.5R_Trail1.8R_2Slots", "sl_mult": 1.8, "rr": 2.5, "be_r": 1.4, "trailing_r": 1.8, "slots": 2},
    {"name": "Runner_1.8ATR_2.2R_4H_Trend_2Slots", "sl_mult": 1.8, "rr": 2.2, "be_r": 1.4, "use_4h": True, "slots": 2},
    {"name": "Runner_1.8ATR_2.5R_4H_Trend_2Slots", "sl_mult": 1.8, "rr": 2.5, "be_r": 1.4, "use_4h": True, "slots": 2},
    {"name": "Runner_1.8ATR_2.2R_Vol_2Slots", "sl_mult": 1.8, "rr": 2.2, "be_r": 1.4, "use_vol": True, "slots": 2},
]

print("\n--- Running Optimization Matrix ---")
final_results = []
for c in configs_to_test:
    res = evaluate_config(c)
    final_results.append(res)
    print(f"[{res['name']}] Oct: ${res['oct_net']:+.2f} (WR {res['oct_wr']}%, DD ${res['oct_dd']}) | YTD: ${res['ytd_net']:+.2f} (WR {res['ytd_wr']}%, DD ${res['ytd_dd']}, PF {res['ytd_pf']})")

print("\n\n" + "=" * 115)
print("                          FINAL CHAMPION SELECTION RANKING")
print("=" * 115)
print(f"{'Strategy Name':<38} | {'Oct Net':<9} | {'Oct WR':<7} | {'Oct DD':<8} | {'YTD Net':<11} | {'YTD WR':<7} | {'YTD DD':<8} | {'YTD PF':<6}")
print("-" * 115)
for r in sorted(final_results, key=lambda x: (x["oct_net"] * 3 + x["ytd_net"]), reverse=True):
    print(f"{r['name']:<38} | ${r['oct_net']:<+8.2f} | {r['oct_wr']:<6.1f}% | ${r['oct_dd']:<7.2f} | ${r['ytd_net']:<+10.2f} | {r['ytd_wr']:<6.1f}% | ${r['ytd_dd']:<7.2f} | {r['ytd_pf']:<6}")
print("=" * 115)

with open("champion_results.json", "w") as f:
    json.dump(final_results, f, indent=2)
