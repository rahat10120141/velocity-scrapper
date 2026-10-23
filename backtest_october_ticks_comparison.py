"""
VELOCITY SCALPER: Multi-Strategy Evaluation on October 3-23, 2026 Live Recorded Ticks
Replays 1,226,118 real 5-second tick snapshots across BTC, ETH, SOL, BNB, LINK.
Evaluates:
  1. Current Production Baseline
  2. ADX Trend Guardian (ADX >= 22 + DI filter + Volume)
  3. MTF Pullback-to-Value (4H Trend + 1H Pullback)
  4. Adaptive Regime-Switch (Trend when ADX>=22, Mean Reversion when ADX<22)
  5. Supertrend Trailing Scalper
"""
import glob
import os
import json
import numpy as np
import pandas as pd
import datetime

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

print("Loading cached 1h, 15m, and 4h historical bars for indicators...")
klines_1h = {}
klines_4h = {}
for s in SYMBOLS:
    df_1h = pd.read_csv(f"data/klines/{s}_1h_2026.csv", index_col=0, parse_dates=True)
    df_4h = pd.read_csv(f"data/klines/{s}_4h_2026.csv", index_col=0, parse_dates=True)
    klines_1h[s] = df_1h
    klines_4h[s] = df_4h

def compute_technical_indicators(df_1h, df_4h):
    df = df_1h.copy()
    c = df["close"]
    h = df["high"]
    l = df["low"]
    v = df["volume"]
    
    # 1. EMAs
    df["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df["ema_21"] = c.ewm(span=21, adjust=False).mean()
    df["ema_50"] = c.ewm(span=50, adjust=False).mean()
    df["ema_200"] = c.ewm(span=200, adjust=False).mean()
    
    # 2. True Range & ATR(14)
    c_prev = c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - c_prev).abs(), (l - c_prev).abs()))
    df["atr"] = tr.rolling(14).mean()
    
    # 3. RSI(14)
    delta = c.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))
    
    # 4. ADX(14), +DI, -DI (Wilder)
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
    
    # 5. Bollinger Bands (20, 2.0)
    df["bb_mid"] = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + (bb_std * 2.0)
    df["bb_lower"] = df["bb_mid"] - (bb_std * 2.0)
    
    # 6. Volume SMA(20)
    df["vol_sma"] = v.rolling(20).mean()
    df["vol_ratio"] = v / (df["vol_sma"] + 1e-9)
    
    # 7. 4H Macro Trend Integration
    df_4h_c = df_4h["close"]
    df_4h_ema50 = df_4h_c.ewm(span=50, adjust=False).mean()
    # Reindex 4H EMA to 1H (forward fill so no lookahead bias)
    df["macro_4h_trend"] = df_4h_ema50.reindex(df.index, method="ffill")
    df["macro_4h_bull"] = df["close"] > df["macro_4h_trend"]
    
    # 8. Supertrend (10, 3.0)
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
                
    df["supertrend_dir"] = st_dir
    return df

prepared_indicators = {}
for s in SYMBOLS:
    prepared_indicators[s] = compute_technical_indicators(klines_1h[s], klines_4h[s])

print("Indicators prepared for all 5 pairs.")

# Load October Live Recorded Ticks
print("Loading and indexing October live recorded tick files...")
tick_files = sorted(glob.glob("data/ticks/*_2026-10-*.csv"))

# Parse ticks grouped by symbol
ticks_by_sym = {s: [] for s in SYMBOLS}
for f in tick_files:
    fname = os.path.basename(f)
    sym = fname.split("_")[0]
    if sym in ticks_by_sym:
        df_tick = pd.read_csv(f, usecols=["timestamp_utc", "price"])
        ticks_by_sym[sym].append(df_tick)

for s in SYMBOLS:
    if ticks_by_sym[s]:
        merged = pd.concat(ticks_by_sym[s], ignore_index=True)
        merged["dt"] = pd.to_datetime(merged["timestamp_utc"])
        merged.drop_duplicates(subset=["dt"], inplace=True)
        merged.sort_values("dt", inplace=True)
        ticks_by_sym[s] = merged
        print(f"  {s}: {len(merged):,} ticks ({merged['dt'].iloc[0]} to {merged['dt'].iloc[-1]})")

# Create a master synchronized tick timeline
all_times = sorted(list(set.union(*[set(df["dt"]) for df in ticks_by_sym.values()])))
print(f"Master timeline created: {len(all_times):,} synchronized tick steps.")

# Strategy Signal Generators (evaluated at 1H bar close, executed on subsequent 5s ticks)
def generate_signals(strategy_name, df):
    c = df["close"]
    ema9 = df["ema_9"]
    ema21 = df["ema_21"]
    ema50 = df["ema_50"]
    ema200 = df["ema_200"]
    atr = df["atr"]
    rsi = df["rsi"]
    adx = df["adx"]
    plus_di = df["plus_di"]
    minus_di = df["minus_di"]
    vol_ratio = df["vol_ratio"]
    bb_upper = df["bb_upper"]
    bb_lower = df["bb_lower"]
    bb_mid = df["bb_mid"]
    macro_bull = df["macro_4h_bull"]
    st_dir = df["supertrend_dir"]
    
    signals = pd.Series(0, index=df.index)
    sl_mults = pd.Series(1.8, index=df.index)
    rr_ratios = pd.Series(2.2, index=df.index)
    be_modes = pd.Series("early_be", index=df.index)
    
    cross_up = (ema9 > ema21) & (ema9.shift(1) <= ema21.shift(1))
    cross_down = (ema9 < ema21) & (ema9.shift(1) >= ema21.shift(1))
    
    if strategy_name == "Current_Baseline":
        # 1H 9/21 cross, 200 EMA regime, RSI 45-68 / 32-55
        buy = (c > ema200) & cross_up & (rsi > 45) & (rsi < 68)
        sell = (c < ema200) & cross_down & (rsi > 32) & (rsi < 55)
        signals[buy] = 1
        signals[sell] = -1
        sl_mults[:] = 1.8
        rr_ratios[:] = 2.2
        be_modes[:] = "early_be"
        
    elif strategy_name == "ADX_Trend_Guardian":
        # Trend filter: ADX > 22, +DI > -DI, Volume Surge > 1.0, RSI 48-65
        adx_trend = adx >= 22
        buy = (c > ema200) & cross_up & (rsi > 48) & (rsi < 65) & adx_trend & (plus_di > minus_di) & (vol_ratio >= 1.0)
        sell = (c < ema200) & cross_down & (rsi > 35) & (rsi < 52) & adx_trend & (minus_di > plus_di) & (vol_ratio >= 1.0)
        signals[buy] = 1
        signals[sell] = -1
        sl_mults[:] = 1.5
        rr_ratios[:] = 2.5
        be_modes[:] = "ladder" # Ladder-lock profit protection
        
    elif strategy_name == "MTF_Pullback_Sniper":
        # 4H Trend Bias + 1H Pullback to 21 EMA / 50 EMA value zone
        # Buy: 4H Bullish + 1H Price touched 21 EMA recently (low <= ema21) + closed back above ema9 + RSI curling up from 40-58
        pullback_buy = (df["low"].rolling(3).min() <= ema21) & (c > ema9) & (c > ema50) & macro_bull & (rsi > 42) & (rsi < 60) & (c.shift(1) <= ema9.shift(1))
        pullback_sell = (df["high"].rolling(3).max() >= ema21) & (c < ema9) & (c < ema50) & (~macro_bull) & (rsi > 40) & (rsi < 58) & (c.shift(1) >= ema9.shift(1))
        signals[pullback_buy] = 1
        signals[pullback_sell] = -1
        sl_mults[:] = 1.2 # Tight stop loss because entry is at dynamic value
        rr_ratios[:] = 2.8 # High R:R
        be_modes[:] = "trailing"
        
    elif strategy_name == "Adaptive_Regime_Switch":
        # Regime A (ADX >= 22): Trend Momentum (9/21 cross with 200 EMA)
        trend_buy = (adx >= 22) & (c > ema200) & cross_up & (rsi > 45) & (rsi < 65) & (plus_di > minus_di)
        trend_sell = (adx >= 22) & (c < ema200) & cross_down & (rsi > 35) & (rsi < 55) & (minus_di > plus_di)
        
        # Regime B (ADX < 22): Choppy Range Mean-Reversion (Bollinger Bands bounce)
        range_buy = (adx < 22) & (df["low"] <= bb_lower) & (c > bb_lower) & (rsi < 38)
        range_sell = (adx < 22) & (df["high"] >= bb_upper) & (c < bb_upper) & (rsi > 62)
        
        signals[trend_buy | range_buy] = 1
        signals[trend_sell | range_sell] = -1
        
        # If range trade, tighter SL and quick TP
        sl_mults[range_buy | range_sell] = 1.0
        rr_ratios[range_buy | range_sell] = 1.4
        sl_mults[trend_buy | trend_sell] = 1.5
        rr_ratios[trend_buy | trend_sell] = 2.4
        be_modes[:] = "ladder"
        
    elif strategy_name == "Supertrend_Vol_Breakout":
        # Supertrend Flip with Volume Surge
        st_flip_up = (st_dir == 1) & (st_dir.shift(1) == -1) & (vol_ratio >= 1.1)
        st_flip_down = (st_dir == -1) & (st_dir.shift(1) == 1) & (vol_ratio >= 1.1)
        signals[st_flip_up] = 1
        signals[st_flip_down] = -1
        sl_mults[:] = 1.6
        rr_ratios[:] = 2.4
        be_modes[:] = "trailing"

    return signals, sl_mults, rr_ratios, be_modes

def run_tick_simulation(strategy_name, max_slots=2, initial_balance=100.0, margin_per_trade=25.0, leverage=5):
    # Pre-generate signals for each symbol
    sym_signals = {}
    for s in SYMBOLS:
        df_ind = prepared_indicators[s]
        sig, slm, rrr, bem = generate_signals(strategy_name, df_ind)
        sym_signals[s] = {
            "df": df_ind,
            "signal": sig,
            "sl_mult": slm,
            "rr_ratio": rrr,
            "be_mode": bem
        }
        
    # Convert tick data into indexed fast lookup dicts: {sym: {dt: price}}
    print(f"\n--- Running Tick Simulation: {strategy_name} (Max Slots: {max_slots}) ---")
    tick_lookup = {}
    for s in SYMBOLS:
        df = ticks_by_sym[s]
        tick_lookup[s] = dict(zip(df["dt"], df["price"]))
        
    balance = initial_balance
    peak_balance = initial_balance
    max_dd = 0.0
    fee_rate = 0.0004 # 0.04% taker fee
    
    active_positions = []
    closed_trades = []
    daily_pnl = {}
    
    # Track hourly bar transitions to check for new entries
    prev_hour = None
    
    # Step through every synchronized tick
    for t in all_times:
        curr_hour = t.floor("1h")
        date_str = str(t)[:10]
        daily_pnl.setdefault(date_str, 0.0)
        
        # 1. Update & evaluate all active positions on this 5-second tick
        surviving = []
        for pos in active_positions:
            s = pos["symbol"]
            curr_p = tick_lookup[s].get(t)
            if curr_p is None:
                surviving.append(pos)
                continue
                
            d = pos["direction"]
            en_p = pos["entry_price"]
            sl_dist = pos["sl_dist"]
            q = pos["quantity"]
            be_mode = pos["be_mode"]
            closed = False
            exit_p = curr_p
            reason = ""
            
            if d == 1: # LONG
                # Track MFE
                if curr_p > pos["peak_p"]:
                    pos["peak_p"] = curr_p
                gain_r = (curr_p - en_p) / sl_dist if sl_dist > 0 else 0
                gain_pct = (curr_p - en_p) / en_p
                
                # Dynamic Profit Protection / Ladder / Trailing
                if be_mode == "early_be":
                    if not pos["be_locked"] and gain_pct >= 0.0060:
                        pos["sl_price"] = en_p * 1.0018
                        pos["be_locked"] = True
                elif be_mode == "ladder":
                    # Step 1: +1.2R -> lock +0.5R
                    if gain_r >= 1.2 and pos["ladder_step"] < 1:
                        pos["sl_price"] = en_p + (0.5 * sl_dist)
                        pos["ladder_step"] = 1
                        pos["be_locked"] = True
                    # Step 2: +1.8R -> lock +1.2R
                    elif gain_r >= 1.8 and pos["ladder_step"] < 2:
                        pos["sl_price"] = en_p + (1.2 * sl_dist)
                        pos["ladder_step"] = 2
                elif be_mode == "trailing":
                    if gain_pct >= 0.0100: # +1.0% triggers trail
                        pos["be_locked"] = True
                        trail_target = pos["peak_p"] * (1.0 - 0.0040)
                        if trail_target > pos["sl_price"]:
                            pos["sl_price"] = trail_target
                            
                # Check Exits on Tick
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
            else: # SHORT
                if curr_p < pos["peak_p"]:
                    pos["peak_p"] = curr_p
                gain_r = (en_p - curr_p) / sl_dist if sl_dist > 0 else 0
                gain_pct = (en_p - curr_p) / en_p
                
                if be_mode == "early_be":
                    if not pos["be_locked"] and gain_pct >= 0.0060:
                        pos["sl_price"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                elif be_mode == "ladder":
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
                        trail_target = pos["peak_p"] * (1.0 + 0.0040)
                        if trail_target < pos["sl_price"]:
                            pos["sl_price"] = trail_target
                            
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
                daily_pnl[date_str] += net
                if balance > peak_balance:
                    peak_balance = balance
                dd = peak_balance - balance
                if dd > max_dd:
                    max_dd = dd
                    
                closed_trades.append({
                    "symbol": s,
                    "direction": "LONG" if d == 1 else "SHORT",
                    "entry_time": pos["entry_time"],
                    "exit_time": str(t),
                    "entry_price": en_p,
                    "exit_price": exit_p,
                    "gross_pnl": round(gross, 2),
                    "fees": round(fees, 2),
                    "net_pnl": round(net, 2),
                    "reason": reason
                })
            else:
                surviving.append(pos)
                
        active_positions = surviving
        
        # 2. Check for New Entries on 1H bar close
        if curr_hour != prev_hour:
            prev_hour = curr_hour
            # Inspect bar that just closed
            eval_time = curr_hour - pd.Timedelta(hours=1)
            
            if len(active_positions) < max_slots:
                open_symbols = {p["symbol"] for p in active_positions}
                for s in SYMBOLS:
                    if s in open_symbols:
                        continue
                    if len(active_positions) >= max_slots:
                        break
                        
                    sig_data = sym_signals[s]
                    df_s = sig_data["df"]
                    
                    if eval_time in df_s.index:
                        sig = sig_data["signal"].loc[eval_time]
                        if sig != 0:
                            curr_tick_p = tick_lookup[s].get(t)
                            if curr_tick_p is None:
                                continue
                                
                            atr_val = df_s.loc[eval_time, "atr"]
                            if pd.isna(atr_val) or atr_val <= 0:
                                continue
                                
                            sl_m = sig_data["sl_mult"].loc[eval_time]
                            rr_m = sig_data["rr_ratio"].loc[eval_time]
                            be_m = sig_data["be_mode"].loc[eval_time]
                            
                            sl_dist = sl_m * atr_val
                            tp_dist = rr_m * sl_dist
                            
                            notional = margin_per_trade * leverage # $125
                            qty = notional / curr_tick_p
                            
                            if sig == 1: # BUY
                                sl_price = curr_tick_p - sl_dist
                                tp_price = curr_tick_p + tp_dist
                            else: # SELL
                                sl_price = curr_tick_p + sl_dist
                                tp_price = curr_tick_p - tp_dist
                                
                            new_pos = {
                                "symbol": s,
                                "direction": sig,
                                "entry_time": str(t),
                                "entry_price": curr_tick_p,
                                "quantity": qty,
                                "sl_dist": sl_dist,
                                "sl_price": sl_price,
                                "tp_price": tp_price,
                                "be_locked": False,
                                "ladder_step": 0,
                                "peak_p": curr_tick_p,
                                "be_mode": be_m
                            }
                            active_positions.append(new_pos)
                            open_symbols.add(s)

    # Compute Final Performance Metrics
    total_trades = len(closed_trades)
    if total_trades == 0:
        return {
            "strategy": strategy_name,
            "net_pnl": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_dd": 0.0,
            "fees": 0.0
        }
        
    wins = [t for t in closed_trades if t["net_pnl"] > 0]
    losses = [t for t in closed_trades if t["net_pnl"] < 0]
    bes = [t for t in closed_trades if t["reason"] == "BREAK_EVEN"]
    sls = [t for t in closed_trades if t["reason"] == "STOP_LOSS"]
    tps = [t for t in closed_trades if t["reason"] == "TAKE_PROFIT"]
    
    tot_win_usd = sum(t["net_pnl"] for t in wins)
    tot_loss_usd = abs(sum(t["net_pnl"] for t in losses))
    profit_factor = round(tot_win_usd / tot_loss_usd, 2) if tot_loss_usd > 0 else 999.0
    win_rate = round(len(wins) / total_trades * 100, 1)
    net_pnl = round(balance - initial_balance, 2)
    tot_fees = round(sum(t["fees"] for t in closed_trades), 2)
    max_dd_pct = round(max_dd / peak_balance * 100, 2)
    
    # Days profitable vs unprofitable
    active_days = [v for k, v in daily_pnl.items() if v != 0]
    win_days = [v for v in active_days if v > 0]
    loss_days = [v for v in active_days if v < 0]
    
    print(f"RESULTS FOR {strategy_name}:")
    print(f"  Net PnL: ${net_pnl:+.2f} | Final Balance: ${balance:.2f}")
    print(f"  Trades: {total_trades} (Wins: {len(wins)}, Losses: {len(losses)}) | Win Rate: {win_rate}%")
    print(f"  Exit Breakdown: {len(tps)} TP, {len(bes)} BE, {len(sls)} SL")
    print(f"  Profit Factor: {profit_factor} | Total Fees Paid: ${tot_fees:.2f}")
    print(f"  Max Drawdown: ${max_dd:.2f} ({max_dd_pct}%)")
    print(f"  Daily Record: {len(win_days)} Green Days / {len(loss_days)} Red Days")
    
    return {
        "strategy": strategy_name,
        "net_pnl": net_pnl,
        "final_balance": round(balance, 2),
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "take_profits": len(tps),
        "break_evens": len(bes),
        "stop_losses": len(sls),
        "fees": tot_fees,
        "max_dd_usd": round(max_dd, 2),
        "max_dd_pct": max_dd_pct,
        "green_days": len(win_days),
        "red_days": len(loss_days),
        "trades": closed_trades
    }

# Execute all strategies
strategies_to_test = [
    "Current_Baseline",
    "ADX_Trend_Guardian",
    "MTF_Pullback_Sniper",
    "Adaptive_Regime_Switch",
    "Supertrend_Vol_Breakout"
]

results = []
for strat in strategies_to_test:
    res = run_tick_simulation(strat, max_slots=2)
    results.append(res)

with open("october_ticks_results.json", "w") as f:
    # Save results without raw trades to keep file light
    summary = [{k: v for k, v in r.items() if k != "trades"} for r in results]
    json.dump(summary, f, indent=2)

print("\n--- OCTOBER 2026 LIVE TICK REPLAY SUMMARY RANKING ---")
print(f"{'Strategy':<26} | {'Net PnL':<10} | {'Win Rate':<10} | {'Trades':<8} | {'PF':<6} | {'Max DD':<10} | {'Fees':<8}")
print("-" * 88)
for r in sorted(results, key=lambda x: x["net_pnl"], reverse=True):
    print(f"{r['strategy']:<26} | ${r['net_pnl']:<+9.2f} | {r['win_rate']:<9.1f}% | {r['total_trades']:<8} | {r['profit_factor']:<6} | ${r['max_dd_usd']:<9.2f} | ${r['fees']:<7.2f}")
