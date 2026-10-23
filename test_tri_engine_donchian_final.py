"""
VELOCITY SCALPER: Tri-Engine Donchian Turtle-Surfer Multi-Year Simulation
Simulates the 3 specialized engines running concurrently:
  Engine 1: RUNNER (20h Donchian + 200 EMA + 2.6R TP + 1.2R BE)
  Engine 2: LADDER (16h Donchian + 100 EMA + 3-Stage Ladder Lock)
  Engine 3: TRAILING (20h Donchian + Supertrend + 0.6 ATR Dynamic Trailing)

Tested across:
  1. Full Year 2025 (365 days)
  2. Full Year 2026 (296 days)
  3. October 2026 Live Recorded Period (23 days)
Budget: $100 per engine ($300 total portfolio) | Risk: $3.00 per trade
"""
import pandas as pd
import numpy as np
import json

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

# Load 2025 and 2026 data
dfs_full = {}
for s in SYMBOLS:
    df25 = pd.read_csv(f"data/klines/{s}_1h_2025.csv", index_col=0, parse_dates=True)
    df26 = pd.read_csv(f"data/klines/{s}_1h_2026.csv", index_col=0, parse_dates=True)
    combined = pd.concat([df25, df26])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined.sort_index(inplace=True)
    dfs_full[s] = combined

def run_engine_sim(engine_name, start_date, end_date):
    start_dt = pd.Timestamp(start_date + " 00:00:00+00:00")
    end_dt = pd.Timestamp(end_date + " 23:59:59+00:00")
    
    risk_usd = 3.0
    fee_rate = 0.0004
    all_dates = sorted(list(set.union(*[set(df.index) for df in dfs_full.values()])))
    sim_dates = [d for d in all_dates if d >= start_dt and d <= end_dt]
    
    # Precompute indicators
    ind_data = {}
    for s in SYMBOLS:
        df = dfs_full[s]
        c, h, l = df["close"], df["high"], df["low"]
        
        period_entry = 16 if engine_name == "ladder" else 20
        trend_ema = c.ewm(span=100 if engine_name == "ladder" else 200, adjust=False).mean()
        high_ch = h.rolling(period_entry).max().shift(1)
        low_ch = l.rolling(period_entry).min().shift(1)
        
        prev_c = c.shift(1)
        tr = np.maximum(h - l, np.maximum((h - prev_c).abs(), (l - prev_c).abs()))
        atr = tr.rolling(14).mean()
        
        ind_data[s] = {
            "c": c, "h": h, "l": l, "o": df["open"],
            "trend": trend_ema, "high_ch": high_ch, "low_ch": low_ch, "atr": atr
        }
        
    balance = 100.0
    peak = 100.0
    max_dd = 0.0
    active_pos = []
    closed_trades = []
    daily_pnl = {}
    max_slots = 2
    
    for t in sim_dates:
        date_str = str(t)[:10]
        daily_pnl.setdefault(date_str, 0.0)
        
        # 1. Manage active positions
        surviving = []
        for pos in active_pos:
            s = pos["symbol"]
            d_s = ind_data[s]
            if t not in d_s["c"].index:
                surviving.append(pos)
                continue
            cur_h = d_s["h"].loc[t]
            cur_l = d_s["l"].loc[t]
            d = pos["direction"]
            en_p = pos["entry_p"]
            sl_dist = pos["sl_dist"]
            q = pos["qty"]
            closed = False
            exit_p = d_s["c"].loc[t]
            
            if d == 1:
                if cur_h > pos["peak_p"]:
                    pos["peak_p"] = cur_h
                gain_r = (cur_h - en_p) / sl_dist if sl_dist > 0 else 0
                
                if engine_name == "runner":
                    if gain_r >= 1.2 and not pos["be_locked"]:
                        pos["sl_p"] = en_p * 1.0018
                        pos["be_locked"] = True
                elif engine_name == "ladder":
                    if gain_r >= 1.0 and pos["step"] < 1:
                        pos["sl_p"] = en_p + (0.5 * sl_dist)
                        pos["step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["step"] < 2:
                        pos["sl_p"] = en_p + (1.2 * sl_dist)
                        pos["step"] = 2
                elif engine_name == "trailing":
                    if gain_r >= 1.2 and not pos["be_locked"]:
                        pos["sl_p"] = en_p * 1.0018
                        pos["be_locked"] = True
                    if gain_r >= 1.6:
                        trail_p = pos["peak_p"] - (0.6 * sl_dist)
                        if trail_p > pos["sl_p"]:
                            pos["sl_p"] = trail_p
                            
                if cur_h >= pos["tp_p"]:
                    exit_p = pos["tp_p"]
                    closed = True
                elif cur_l <= pos["sl_p"]:
                    exit_p = pos["sl_p"]
                    closed = True
                    
                if closed:
                    pnl = (exit_p - en_p) * q - (en_p + exit_p) * q * fee_rate
            else:
                if cur_l < pos["peak_p"]:
                    pos["peak_p"] = cur_l
                gain_r = (en_p - cur_l) / sl_dist if sl_dist > 0 else 0
                
                if engine_name == "runner":
                    if gain_r >= 1.2 and not pos["be_locked"]:
                        pos["sl_p"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                elif engine_name == "ladder":
                    if gain_r >= 1.0 and pos["step"] < 1:
                        pos["sl_p"] = en_p - (0.5 * sl_dist)
                        pos["step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["step"] < 2:
                        pos["sl_p"] = en_p - (1.2 * sl_dist)
                        pos["step"] = 2
                elif engine_name == "trailing":
                    if gain_r >= 1.2 and not pos["be_locked"]:
                        pos["sl_p"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                    if gain_r >= 1.6:
                        trail_p = pos["peak_p"] + (0.6 * sl_dist)
                        if trail_p < pos["sl_p"]:
                            pos["sl_p"] = trail_p
                            
                if cur_l <= pos["tp_p"]:
                    exit_p = pos["tp_p"]
                    closed = True
                elif cur_h >= pos["sl_p"]:
                    exit_p = pos["sl_p"]
                    closed = True
                    
                if closed:
                    pnl = (en_p - exit_p) * q - (en_p + exit_p) * q * fee_rate
                    
            if closed:
                balance += pnl
                daily_pnl[date_str] += pnl
                if balance > peak:
                    peak = balance
                dd = peak - balance
                if dd > max_dd:
                    max_dd = dd
                closed_trades.append(pnl)
            else:
                surviving.append(pos)
                
        active_pos = surviving
        
        # 2. Check for new entries
        if len(active_pos) < max_slots:
            open_s = {p["symbol"] for p in active_pos}
            for s in SYMBOLS:
                if s in open_s or len(active_pos) >= max_slots:
                    continue
                d_s = ind_data[s]
                if t in d_s["c"].index:
                    cur_c = d_s["c"].loc[t]
                    cur_h = d_s["h"].loc[t]
                    cur_l = d_s["l"].loc[t]
                    trend_val = d_s["trend"].loc[t]
                    h_ch = d_s["high_ch"].loc[t]
                    l_ch = d_s["low_ch"].loc[t]
                    atr_val = d_s["atr"].loc[t]
                    
                    if pd.isna(atr_val) or atr_val <= 0 or pd.isna(h_ch) or pd.isna(l_ch):
                        continue
                        
                    sig = 0
                    if cur_h > h_ch and cur_c > trend_val:
                        sig = 1
                    elif cur_l < l_ch and cur_c < trend_val:
                        sig = -1
                        
                    if sig != 0:
                        sl_mult = 1.8 if engine_name != "ladder" else 1.5
                        rr = 2.6 if engine_name == "runner" else (2.4 if engine_name == "ladder" else 2.8)
                        sl_d = sl_mult * atr_val
                        tp_d = rr * sl_d
                        q = risk_usd / sl_d
                        
                        en_p = h_ch if sig == 1 else l_ch
                        sl_p = en_p - sl_d if sig == 1 else en_p + sl_d
                        tp_p = en_p + tp_d if sig == 1 else en_p - tp_d
                        
                        active_pos.append({
                            "symbol": s,
                            "direction": sig,
                            "entry_p": en_p,
                            "qty": q,
                            "sl_dist": sl_d,
                            "sl_p": sl_p,
                            "tp_p": tp_p,
                            "be_locked": False,
                            "step": 0,
                            "peak_p": en_p
                        })
                        open_s.add(s)

    tot_tr = len(closed_trades)
    if tot_tr == 0:
        return {"net": 0, "wr": 0, "trades": 0, "dd": 0, "daily_avg": 0}
    wins = [x for x in closed_trades if x > 0]
    wr = round(len(wins) / tot_tr * 100, 1)
    net = round(balance - 100.0, 2)
    days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 1
    daily_avg = round(net / days, 2)
    gp = sum(wins)
    gl = abs(sum([x for x in closed_trades if x < 0]))
    pf = round(gp / gl, 2) if gl > 0 else 999.0
    
    return {
        "engine": engine_name.upper(),
        "net": net,
        "wr": wr,
        "trades": tot_tr,
        "dd": round(max_dd, 2),
        "daily_avg": daily_avg,
        "pf": pf
    }

print("\n==========================================================================================")
print("             TRI-ENGINE DONCHIAN TURTLE-SURFER COMPREHENSIVE AUDIT")
print("==========================================================================================")

periods = [
    ("2025 Full Year", "2025-01-01", "2025-12-31"),
    ("2026 Year-to-Date", "2026-01-01", "2026-10-23"),
    ("October 2026 Live Ticks", "2026-10-01", "2026-10-23")
]

all_res = []
for p_label, s_dt, e_dt in periods:
    print(f"\n--- PERIOD: {p_label} ({s_dt} to {e_dt}) ---")
    p_tot_net = 0
    p_tot_daily = 0
    for eng in ["runner", "ladder", "trailing"]:
        r = run_engine_sim(eng, s_dt, e_dt)
        p_tot_net += r["net"]
        p_tot_daily += r["daily_avg"]
        print(f"  {r['engine']:<10}: Net: ${r['net']:<+8.2f} | WR: {r['wr']:<5.1f}% | Trades: {r['trades']:<5} | PF: {r['pf']:<5} | DD: ${r['dd']:<6} | Avg: ${r['daily_avg']}/day")
    print(f"  >> COMBINED 3 ENGINES: Net: ${p_tot_net:+.2f} | Combined Daily Profit: ${p_tot_daily:+.2f}/day <<")
    all_res.append({"period": p_label, "total_net": round(p_tot_net, 2), "daily_avg": round(p_tot_daily, 2)})

print("\n" + "=" * 90)
