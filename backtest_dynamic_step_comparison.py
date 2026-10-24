"""
VELOCITY SCALPER: Direct Head-to-Head Comparative Backtest Audit
Compares:
  Model A [PREVIOUS]: Fixed +2.6R TP ceiling, Late BE/Step at +1.0R/+1.2R
  Model B [NEW STEPPING]: Early $1.00 Lock @ $1.20, Dynamic Stepping Ratchet ($1.60, $2.80, $4.50, $7.80, 80% Trail to $25+)
Tested across 5 pairs: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, LINKUSDT (1-hour bars)
"""
import os
import json
import pandas as pd
import numpy as np

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

# Load 2025 and 2026 kline data
dfs_full = {}
for s in SYMBOLS:
    p25 = f"data/klines/{s}_1h_2025.csv"
    p26 = f"data/klines/{s}_1h_2026.csv"
    if os.path.exists(p25) and os.path.exists(p26):
        df25 = pd.read_csv(p25, index_col=0, parse_dates=True)
        df26 = pd.read_csv(p26, index_col=0, parse_dates=True)
        combined = pd.concat([df25, df26])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
        dfs_full[s] = combined

def run_simulation(strategy_mode="NEW", start_date="2025-01-01", end_date="2026-10-23", max_slots=3):
    start_dt = pd.Timestamp(start_date + " 00:00:00+00:00")
    end_dt = pd.Timestamp(end_date + " 23:59:59+00:00")
    
    risk_usd = 3.00
    fee_rate = 0.0004
    all_dates = sorted(list(set.union(*[set(df.index) for df in dfs_full.values()])))
    sim_dates = [d for d in all_dates if d >= start_dt and d <= end_dt]
    
    # Precompute indicators
    ind_data = {}
    for s in SYMBOLS:
        df = dfs_full[s]
        c, h, l = df["close"], df["high"], df["low"]
        trend_ema = c.ewm(span=200, adjust=False).mean()
        high_ch = h.rolling(20).max().shift(1)
        low_ch = l.rolling(20).min().shift(1)
        prev_c = c.shift(1)
        tr = np.maximum(h - l, np.maximum((h - prev_c).abs(), (l - prev_c).abs()))
        atr = tr.rolling(14).mean()
        ind_data[s] = {"c": c, "h": h, "l": l, "trend": trend_ema, "high_ch": high_ch, "low_ch": low_ch, "atr": atr}
        
    balance = 300.0  # $300 portfolio capital
    peak = 300.0
    max_dd = 0.0
    active_pos = []
    closed_trades = []
    
    for t in sim_dates:
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
            exit_reason = ""
            
            if d == 1: # LONG
                if cur_h > pos["peak_p"]:
                    pos["peak_p"] = cur_h
                peak_p = pos["peak_p"]
                peak_gain_usd = (peak_p - en_p) * q
                
                if strategy_mode == "OLD":
                    gain_r = (peak_p - en_p) / sl_dist if sl_dist > 0 else 0
                    # Old: Late BE @ +1.2R, Step Lock @ +1.8R
                    if gain_r >= 1.2 and not pos.get("be_locked"):
                        pos["sl_p"] = en_p * 1.0018
                        pos["be_locked"] = True
                    if gain_r >= 1.8 and not pos.get("step2_locked"):
                        pos["sl_p"] = en_p + (1.2 * sl_dist)
                        pos["step2_locked"] = True
                    # Fixed hard TP @ +2.6R
                    if cur_h >= pos["tp_p"]:
                        exit_p = pos["tp_p"]
                        exit_reason = "TAKE_PROFIT_2.6R"
                        closed = True
                    elif cur_l <= pos["sl_p"]:
                        exit_p = pos["sl_p"]
                        exit_reason = "STOP_LOSS"
                        closed = True
                else: # NEW STEPPING
                    # Dynamic Step-by-Step Dollar Profit Lock
                    locked_usd = 0.0
                    if peak_gain_usd >= 1.20 and peak_gain_usd < 2.50:
                        locked_usd = 0.80
                    elif peak_gain_usd >= 2.50 and peak_gain_usd < 4.00:
                        locked_usd = 1.60
                    elif peak_gain_usd >= 4.00 and peak_gain_usd < 6.00:
                        locked_usd = 2.80
                    elif peak_gain_usd >= 6.00 and peak_gain_usd < 10.00:
                        locked_usd = 4.50
                    elif peak_gain_usd >= 10.00 and peak_gain_usd < 15.00:
                        locked_usd = 7.80
                    elif peak_gain_usd >= 15.00:
                        locked_usd = round(peak_gain_usd * 0.80, 2) # Trail 80% of peak to $25+
                        
                    if locked_usd > 0 and locked_usd > pos.get("step_locked_usd", 0.0):
                        pos["step_locked_usd"] = locked_usd
                        target_sl = round(en_p + (locked_usd / q), 4)
                        if target_sl > pos["sl_p"]:
                            pos["sl_p"] = target_sl
                            
                    # Wide +10R TP allows massive trends to run to $25+
                    if cur_h >= pos["tp_p"]:
                        exit_p = pos["tp_p"]
                        exit_reason = "TAKE_PROFIT_RUNNER"
                        closed = True
                    elif cur_l <= pos["sl_p"]:
                        exit_p = pos["sl_p"]
                        exit_reason = f"PROFIT_LOCK_+${pos.get('step_locked_usd', 0):.2f}" if pos.get('step_locked_usd', 0) > 0 else "STOP_LOSS"
                        closed = True
                        
                if closed:
                    pnl = (exit_p - en_p) * q - (en_p + exit_p) * q * fee_rate
                    
            else: # SHORT
                if cur_l < pos["peak_p"]:
                    pos["peak_p"] = cur_l
                peak_p = pos["peak_p"]
                peak_gain_usd = (en_p - peak_p) * q
                
                if strategy_mode == "OLD":
                    gain_r = (en_p - peak_p) / sl_dist if sl_dist > 0 else 0
                    if gain_r >= 1.2 and not pos.get("be_locked"):
                        pos["sl_p"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                    if gain_r >= 1.8 and not pos.get("step2_locked"):
                        pos["sl_p"] = en_p - (1.2 * sl_dist)
                        pos["step2_locked"] = True
                    if cur_l <= pos["tp_p"]:
                        exit_p = pos["tp_p"]
                        exit_reason = "TAKE_PROFIT_2.6R"
                        closed = True
                    elif cur_h >= pos["sl_p"]:
                        exit_p = pos["sl_p"]
                        exit_reason = "STOP_LOSS"
                        closed = True
                else: # NEW STEPPING
                    locked_usd = 0.0
                    if peak_gain_usd >= 1.20 and peak_gain_usd < 2.50:
                        locked_usd = 0.80
                    elif peak_gain_usd >= 2.50 and peak_gain_usd < 4.00:
                        locked_usd = 1.60
                    elif peak_gain_usd >= 4.00 and peak_gain_usd < 6.00:
                        locked_usd = 2.80
                    elif peak_gain_usd >= 6.00 and peak_gain_usd < 10.00:
                        locked_usd = 4.50
                    elif peak_gain_usd >= 10.00 and peak_gain_usd < 15.00:
                        locked_usd = 7.80
                    elif peak_gain_usd >= 15.00:
                        locked_usd = round(peak_gain_usd * 0.80, 2)
                        
                    if locked_usd > 0 and locked_usd > pos.get("step_locked_usd", 0.0):
                        pos["step_locked_usd"] = locked_usd
                        target_sl = round(en_p - (locked_usd / q), 4)
                        if target_sl < pos["sl_p"]:
                            pos["sl_p"] = target_sl
                            
                    if cur_l <= pos["tp_p"]:
                        exit_p = pos["tp_p"]
                        exit_reason = "TAKE_PROFIT_RUNNER"
                        closed = True
                    elif cur_h >= pos["sl_p"]:
                        exit_p = pos["sl_p"]
                        exit_reason = f"PROFIT_LOCK_+${pos.get('step_locked_usd', 0):.2f}" if pos.get('step_locked_usd', 0) > 0 else "STOP_LOSS"
                        closed = True
                        
                if closed:
                    pnl = (en_p - exit_p) * q - (en_p + exit_p) * q * fee_rate
                    
            if closed:
                balance += pnl
                if balance > peak:
                    peak = balance
                dd = peak - balance
                if dd > max_dd:
                    max_dd = dd
                closed_trades.append({"pnl": round(pnl, 2), "reason": exit_reason})
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
                        sl_d = 1.8 * atr_val
                        rr = 2.6 if strategy_mode == "OLD" else 10.0
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
                            "peak_p": en_p,
                            "be_locked": False,
                            "step_locked_usd": 0.0
                        })
                        open_s.add(s)
                        
    tot_tr = len(closed_trades)
    if tot_tr == 0:
        return {"net": 0, "wr": 0, "trades": 0, "dd": 0, "pf": 0}
        
    wins = [x["pnl"] for x in closed_trades if x["pnl"] > 0]
    losses = [x["pnl"] for x in closed_trades if x["pnl"] <= 0]
    wr = round(len(wins) / tot_tr * 100, 1)
    net = round(balance - 300.0, 2)
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = round(gp / gl, 2) if gl > 0 else 999.0
    big_wins = len([x for x in wins if x >= 10.0])
    avg_win = round(np.mean(wins), 2) if wins else 0.0
    avg_loss = round(np.mean(losses), 2) if losses else 0.0
    
    return {
        "mode": strategy_mode,
        "net": net,
        "wr": wr,
        "trades": tot_tr,
        "wins": len(wins),
        "losses": len(losses),
        "big_wins_10plus": big_wins,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "pf": pf,
        "max_dd": round(max_dd, 2),
        "return_pct": round((net / 300.0) * 100, 1)
    }

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("      HEAD-TO-HEAD COMPARATIVE AUDIT: PREVIOUS VS NEW STEPPING STRATEGY")
    print("=" * 80)
    
    test_periods = [
        ("October 2026 (Live Recorded Market - High Volatility)", "2026-10-01", "2026-10-23"),
        ("2026 Year-to-Date (Jan - Oct 2026, 296 Days)", "2026-01-01", "2026-10-23"),
        ("2025 Full Year (365 Days Historical Trend)", "2025-01-01", "2025-12-31"),
        ("Multi-Year Combined (2025 - 2026 Complete, 661 Days)", "2025-01-01", "2026-10-23")
    ]
    
    results = []
    for label, s_dt, e_dt in test_periods:
        print(f"\n>>> TESTING PERIOD: {label} ({s_dt} to {e_dt})")
        old_res = run_simulation("OLD", s_dt, e_dt)
        new_res = run_simulation("NEW", s_dt, e_dt)
        
        diff_net = new_res["net"] - old_res["net"]
        diff_pct = new_res["return_pct"] - old_res["return_pct"]
        diff_wr = new_res["wr"] - old_res["wr"]
        
        print(f"  [PREVIOUS STRATEGY] : Net Profit: ${old_res['net']:<+8.2f} ({old_res['return_pct']:<+5.1f}%) | WR: {old_res['wr']:<5.1f}% | Trades: {old_res['trades']:<4} | PF: {old_res['pf']:<5.2f} | MaxDD: ${old_res['max_dd']:<5.2f} | Trades >=$10: {old_res['big_wins_10plus']}")
        print(f"  [NEW STEPPING LOCK] : Net Profit: ${new_res['net']:<+8.2f} ({new_res['return_pct']:<+5.1f}%) | WR: {new_res['wr']:<5.1f}% | Trades: {new_res['trades']:<4} | PF: {new_res['pf']:<5.2f} | MaxDD: ${new_res['max_dd']:<5.2f} | Trades >=$10: {new_res['big_wins_10plus']}")
        print(f"  --> ADVANTAGE OF NEW : Net Diff: ${diff_net:<+8.2f} | Win Rate Diff: {diff_wr:<+5.1f}% | Big Runners: +{new_res['big_wins_10plus'] - old_res['big_wins_10plus']} trades")
        
        results.append({
            "period": label,
            "old": old_res,
            "new": new_res,
            "diff_net": round(diff_net, 2),
            "diff_wr": round(diff_wr, 1)
        })
        
    with open("comparison_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n" + "=" * 80)
