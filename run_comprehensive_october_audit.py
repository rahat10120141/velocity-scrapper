"""
VELOCITY SCALPER: Ultra-Fast Precision Replay on October 3-23, 2026 Live Recorded Ticks
Replays 1.22M 5-second tick snapshots across BTC, ETH, SOL, BNB, LINK.
Evaluates 7 Quantitative Strategies:
  1. Baseline (Current Production 1H 9/21 EMA + Early BE)
  2. Baseline_Ladder (Current Ladder Engine)
  3. Baseline_Trailing (Current Trailing Engine)
  4. ADX_Trend_Guardian (ADX >= 22 + DI Confirmation + Volume Surge + Ladder Lock)
  5. MTF_Pullback_Sniper (4H Trend Bias + 1H 21-EMA Pullback to Value + 1.2 ATR SL + 2.8R TP)
  6. Adaptive_Regime_Switch (ADX >= 22 Trend + ADX < 22 Bollinger Mean Reversion)
  7. Supertrend_ATR_Breakout (Supertrend 10,3.0 + Volume Surge + Dynamic Trailing)
"""
import glob
import os
import json
import time
import numpy as np
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

print("1. Loading cached 1h and 4h historical bars...")
klines_1h = {}
klines_4h = {}
for s in SYMBOLS:
    df_1h = pd.read_csv(f"data/klines/{s}_1h_2026.csv", index_col=0, parse_dates=True)
    df_4h = pd.read_csv(f"data/klines/{s}_4h_2026.csv", index_col=0, parse_dates=True)
    klines_1h[s] = df_1h
    klines_4h[s] = df_4h

def compute_all_indicators(df_1h, df_4h):
    df = df_1h.copy()
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
    
    # ADX(14), +DI, -DI (Wilder smoothing)
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
    
    # Bollinger Bands (20, 2.0)
    df["bb_mid"] = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + (bb_std * 2.0)
    df["bb_lower"] = df["bb_mid"] - (bb_std * 2.0)
    
    # Volume SMA(20)
    df["vol_sma"] = v.rolling(20).mean()
    df["vol_ratio"] = v / (df["vol_sma"] + 1e-9)
    
    # 4H Macro Trend Integration
    df_4h_c = df_4h["close"]
    df_4h_ema50 = df_4h_c.ewm(span=50, adjust=False).mean()
    df["macro_4h_trend"] = df_4h_ema50.reindex(df.index, method="ffill")
    df["macro_4h_bull"] = df["close"] > df["macro_4h_trend"]
    
    # Supertrend (10, 3.0)
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
    prepared_indicators[s] = compute_all_indicators(klines_1h[s], klines_4h[s])

print("2. Loading October live recorded ticks (UTC normalized)...")
tick_data_by_sym = {}
for s in SYMBOLS:
    files = sorted(glob.glob(f"data/ticks/{s}_2026-10-*.csv"))
    dfs = []
    for f in files:
        df = pd.read_csv(f, usecols=["timestamp_utc", "price"])
        dfs.append(df)
    m = pd.concat(dfs, ignore_index=True)
    m["dt"] = pd.to_datetime(m["timestamp_utc"], utc=True)
    m.dropna(subset=["dt", "price"], inplace=True)
    m.drop_duplicates(subset=["dt"], inplace=True)
    m.sort_values("dt", inplace=True)
    tick_data_by_sym[s] = m
    print(f"  {s}: {len(m):,} ticks ({m['dt'].iloc[0]} to {m['dt'].iloc[-1]})")

# Build unified time series for fast iteration
all_times_utc = sorted(list(set.union(*[set(df["dt"]) for df in tick_data_by_sym.values()])))
print(f"  Total synchronized tick steps: {len(all_times_utc):,}")

# Precompute price arrays for 100x speed
print("  Precomputing price lookups...")
price_lookups = {}
for s in SYMBOLS:
    price_lookups[s] = dict(zip(tick_data_by_sym[s]["dt"], tick_data_by_sym[s]["price"].astype(float)))

def get_strategy_signals(strat_name, df):
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
    macro_bull = df["macro_4h_bull"]
    st_dir = df["supertrend_dir"]
    
    signals = pd.Series(0, index=df.index)
    sl_mults = pd.Series(1.8, index=df.index)
    rr_ratios = pd.Series(2.2, index=df.index)
    be_types = pd.Series("early_be", index=df.index)
    
    cross_up = (ema9 > ema21) & (ema9.shift(1) <= ema21.shift(1))
    cross_down = (ema9 < ema21) & (ema9.shift(1) >= ema21.shift(1))
    
    if strat_name == "Baseline":
        # 1H 9/21 cross + 200 EMA + RSI 45-68
        buy = (c > ema200) & cross_up & (rsi > 45) & (rsi < 68)
        sell = (c < ema200) & cross_down & (rsi > 32) & (rsi < 55)
        signals[buy] = 1
        signals[sell] = -1
        sl_mults[:] = 1.8
        rr_ratios[:] = 2.2
        be_types[:] = "early_be"
        
    elif strat_name == "Baseline_Ladder":
        buy = (c > ema200) & cross_up & (rsi > 45) & (rsi < 68)
        sell = (c < ema200) & cross_down & (rsi > 32) & (rsi < 55)
        signals[buy] = 1
        signals[sell] = -1
        sl_mults[:] = 1.8
        rr_ratios[:] = 2.2
        be_types[:] = "ladder"
        
    elif strat_name == "Baseline_Trailing":
        buy = (c > ema200) & cross_up & (rsi > 45) & (rsi < 68)
        sell = (c < ema200) & cross_down & (rsi > 32) & (rsi < 55)
        signals[buy] = 1
        signals[sell] = -1
        sl_mults[:] = 1.8
        rr_ratios[:] = 2.2
        be_types[:] = "trailing"
        
    elif strat_name == "ADX_Trend_Guardian":
        # Strict trend confirmation: ADX >= 22, +DI > -DI, Volume >= 1.0x, healthy RSI
        trend_regime = adx >= 22
        buy = (c > ema200) & cross_up & trend_regime & (plus_di > minus_di) & (rsi > 48) & (rsi < 65) & (vol_ratio >= 1.0)
        sell = (c < ema200) & cross_down & trend_regime & (minus_di > plus_di) & (rsi > 35) & (rsi < 52) & (vol_ratio >= 1.0)
        signals[buy] = 1
        signals[sell] = -1
        sl_mults[:] = 1.5
        rr_ratios[:] = 2.5
        be_types[:] = "ladder"
        
    elif strat_name == "MTF_Pullback_Sniper":
        # 4H Macro Trend + 1H Value Pullback to 21 EMA
        pullback_buy = (df["low"].rolling(3).min() <= ema21) & (c > ema9) & (c > ema50) & macro_bull & (rsi > 42) & (rsi < 62) & (c.shift(1) <= ema9.shift(1))
        pullback_sell = (df["high"].rolling(3).max() >= ema21) & (c < ema9) & (c < ema50) & (~macro_bull) & (rsi > 38) & (rsi < 58) & (c.shift(1) >= ema9.shift(1))
        signals[pullback_buy] = 1
        signals[pullback_sell] = -1
        sl_mults[:] = 1.2 # Tight stop on value entry
        rr_ratios[:] = 2.8 # High R:R
        be_types[:] = "trailing"
        
    elif strat_name == "Adaptive_Regime_Switch":
        # Trending: ADX >= 22
        trend_buy = (adx >= 22) & (c > ema200) & cross_up & (rsi > 45) & (rsi < 65) & (plus_di > minus_di)
        trend_sell = (adx >= 22) & (c < ema200) & cross_down & (rsi > 35) & (rsi < 55) & (minus_di > plus_di)
        
        # Chopping/Ranging: ADX < 22 -> Bollinger Mean Reversion
        range_buy = (adx < 22) & (df["low"] <= bb_lower) & (c > bb_lower) & (rsi < 38)
        range_sell = (adx < 22) & (df["high"] >= bb_upper) & (c < bb_upper) & (rsi > 62)
        
        signals[trend_buy | range_buy] = 1
        signals[trend_sell | range_sell] = -1
        
        sl_mults[range_buy | range_sell] = 1.0
        rr_ratios[range_buy | range_sell] = 1.4
        sl_mults[trend_buy | trend_sell] = 1.5
        rr_ratios[trend_buy | trend_sell] = 2.4
        be_types[:] = "ladder"
        
    elif strat_name == "Supertrend_ATR_Breakout":
        st_flip_up = (st_dir == 1) & (st_dir.shift(1) == -1) & (vol_ratio >= 1.1)
        st_flip_down = (st_dir == -1) & (st_dir.shift(1) == 1) & (vol_ratio >= 1.1)
        signals[st_flip_up] = 1
        signals[st_flip_down] = -1
        sl_mults[:] = 1.6
        rr_ratios[:] = 2.4
        be_types[:] = "trailing"

    return signals, sl_mults, rr_ratios, be_types

def run_fast_tick_simulation(strat_name, max_slots=2, initial_balance=100.0, margin_per_trade=25.0, leverage=5):
    t_start = time.time()
    
    # Pre-generate signals
    signals_dict = {}
    for s in SYMBOLS:
        df = prepared_indicators[s]
        sig, slm, rrr, bem = get_strategy_signals(strat_name, df)
        signals_dict[s] = {
            "df": df,
            "sig": sig,
            "slm": slm,
            "rrr": rrr,
            "bem": bem
        }
        
    balance = initial_balance
    peak_balance = initial_balance
    max_dd = 0.0
    fee_rate = 0.0004 # 0.04% taker fee
    
    active_positions = []
    closed_trades = []
    daily_pnl = {}
    
    # Map 1h timestamps to their index
    prev_hour_ts = None
    
    for t in all_times_utc:
        curr_hour_ts = t.replace(minute=0, second=0, microsecond=0)
        date_str = str(t)[:10]
        daily_pnl.setdefault(date_str, 0.0)
        
        # 1. Update active positions on current tick
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
            be_type = pos["be_mode"]
            closed = False
            exit_p = curr_p
            reason = ""
            
            if d == 1: # LONG
                if curr_p > pos["peak_p"]:
                    pos["peak_p"] = curr_p
                gain_r = (curr_p - en_p) / sl_dist if sl_dist > 0 else 0
                gain_pct = (curr_p - en_p) / en_p
                
                if be_type == "early_be":
                    if not pos["be_locked"] and gain_pct >= 0.0060:
                        pos["sl_price"] = en_p * 1.0018
                        pos["be_locked"] = True
                elif be_type == "ladder":
                    if gain_r >= 1.2 and pos["ladder_step"] < 1:
                        pos["sl_price"] = en_p + (0.5 * sl_dist)
                        pos["ladder_step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["ladder_step"] < 2:
                        pos["sl_price"] = en_p + (1.2 * sl_dist)
                        pos["ladder_step"] = 2
                elif be_type == "trailing":
                    if gain_pct >= 0.0100:
                        pos["be_locked"] = True
                        trail_target = pos["peak_p"] * (1.0 - 0.0040)
                        if trail_target > pos["sl_price"]:
                            pos["sl_price"] = trail_target
                            
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
                
                if be_type == "early_be":
                    if not pos["be_locked"] and gain_pct >= 0.0060:
                        pos["sl_price"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                elif be_type == "ladder":
                    if gain_r >= 1.2 and pos["ladder_step"] < 1:
                        pos["sl_price"] = en_p - (0.5 * sl_dist)
                        pos["ladder_step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["ladder_step"] < 2:
                        pos["sl_price"] = en_p - (1.2 * sl_dist)
                        pos["ladder_step"] = 2
                elif be_type == "trailing":
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
        if curr_hour_ts != prev_hour_ts:
            prev_hour_ts = curr_hour_ts
            eval_time = curr_hour_ts - pd.Timedelta(hours=1)
            
            if len(active_positions) < max_slots:
                open_symbols = {p["symbol"] for p in active_positions}
                for s in SYMBOLS:
                    if s in open_symbols:
                        continue
                    if len(active_positions) >= max_slots:
                        break
                        
                    s_data = signals_dict[s]
                    df_s = s_data["df"]
                    
                    if eval_time in df_s.index:
                        sig = s_data["sig"].loc[eval_time]
                        if sig != 0:
                            curr_tick_p = price_lookups[s].get(t)
                            if curr_tick_p is None:
                                continue
                                
                            atr_val = df_s.loc[eval_time, "atr"]
                            if pd.isna(atr_val) or atr_val <= 0:
                                continue
                                
                            sl_m = s_data["slm"].loc[eval_time]
                            rr_m = s_data["rrr"].loc[eval_time]
                            be_m = s_data["bem"].loc[eval_time]
                            
                            sl_dist = sl_m * atr_val
                            tp_dist = rr_m * sl_dist
                            
                            notional = margin_per_trade * leverage # $125
                            qty = notional / curr_tick_p
                            
                            if sig == 1:
                                sl_price = curr_tick_p - sl_dist
                                tp_price = curr_tick_p + tp_dist
                            else:
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

    elapsed = time.time() - t_start
    total_trades = len(closed_trades)
    if total_trades == 0:
        print(f"[{strat_name}] 0 trades opened. Elapsed: {elapsed:.1f}s")
        return {"strategy": strat_name, "net_pnl": 0.0, "total_trades": 0, "win_rate": 0, "profit_factor": 0, "max_dd_usd": 0, "fees": 0}
        
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
    
    active_days = [v for k, v in daily_pnl.items() if v != 0]
    win_days = [v for v in active_days if v > 0]
    loss_days = [v for v in active_days if v < 0]
    
    print(f"\n=======================================================")
    print(f"STRATEGY: {strat_name} (Elapsed: {elapsed:.1f}s)")
    print(f"  Net PnL: ${net_pnl:+.2f} | Final Balance: ${balance:.2f}")
    print(f"  Trades: {total_trades} (Wins: {len(wins)}, Losses: {len(losses)}) | Win Rate: {win_rate}%")
    print(f"  Exit Breakdown: {len(tps)} TP, {len(bes)} BE, {len(sls)} SL")
    print(f"  Profit Factor: {profit_factor} | Total Fees Paid: ${tot_fees:.2f}")
    print(f"  Max Drawdown: ${max_dd:.2f} ({max_dd_pct}%)")
    print(f"  Daily Record: {len(win_days)} Green Days / {len(loss_days)} Red Days")
    print(f"=======================================================")
    
    return {
        "strategy": strat_name,
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
        "red_days": len(loss_days)
    }

strats = [
    "Baseline",
    "Baseline_Ladder",
    "Baseline_Trailing",
    "ADX_Trend_Guardian",
    "MTF_Pullback_Sniper",
    "Adaptive_Regime_Switch",
    "Supertrend_ATR_Breakout"
]

all_results = []
for st in strats:
    res = run_fast_tick_simulation(st, max_slots=2)
    all_results.append(res)

print("\n\n" + "=" * 90)
print("           OCTOBER 2026 LIVE TICK REPLAY: MULTI-STRATEGY RANKING REPORT")
print("=" * 90)
print(f"{'Strategy Name':<25} | {'Net PnL':<10} | {'Win Rate':<10} | {'Trades':<8} | {'PF':<6} | {'Max DD':<9} | {'Fees':<7}")
print("-" * 90)
for r in sorted(all_results, key=lambda x: x["net_pnl"], reverse=True):
    print(f"{r['strategy']:<25} | ${r['net_pnl']:<+9.2f} | {r['win_rate']:<9.1f}% | {r['total_trades']:<8} | {r['profit_factor']:<6} | ${r['max_dd_usd']:<8.2f} | ${r['fees']:<6.2f}")
print("=" * 90)

with open("october_replay_final.json", "w") as f:
    json.dump(all_results, f, indent=2)
