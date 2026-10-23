"""
VELOCITY SCALPER: High-Yield Quantitative Strategy Discovery Engine
Explores strategies across 15m and 1h bars with live October tick replay.
Goal: Find strategies with high trade frequency, solid win rate (>60%), low drawdown, and strong daily net profit ($2-$5/day).
"""
import glob
import os
import json
import time
import numpy as np
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

print("Loading 15m, 1h, and 4h historical klines...")
klines_15m = {}
klines_1h = {}
klines_4h = {}

for s in SYMBOLS:
    klines_15m[s] = pd.read_csv(f"data/klines/{s}_15m_2026.csv", index_col=0, parse_dates=True)
    klines_1h[s] = pd.read_csv(f"data/klines/{s}_1h_2026.csv", index_col=0, parse_dates=True)
    klines_4h[s] = pd.read_csv(f"data/klines/{s}_4h_2026.csv", index_col=0, parse_dates=True)

# Load October live ticks
print("Loading October ticks...")
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

all_times_utc = sorted(list(set.union(*[set(df["dt"]) for df in tick_data_by_sym.values()])))
print(f"Master timeline: {len(all_times_utc):,} ticks.")

price_lookups = {}
for s in SYMBOLS:
    price_lookups[s] = dict(zip(tick_data_by_sym[s]["dt"], tick_data_by_sym[s]["price"].astype(float)))

def compute_indicators_df(df_base, df_htf=None):
    df = df_base.copy()
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
    
    # Bollinger Bands
    df["bb_mid"] = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + (bb_std * 2.0)
    df["bb_lower"] = df["bb_mid"] - (bb_std * 2.0)
    
    # Volume SMA(20)
    df["vol_sma"] = v.rolling(20).mean()
    df["vol_ratio"] = v / (df["vol_sma"] + 1e-9)
    
    # HTF Trend
    if df_htf is not None:
        htf_ema50 = df_htf["close"].ewm(span=50, adjust=False).mean()
        df["htf_trend"] = htf_ema50.reindex(df.index, method="ffill")
        df["htf_bull"] = df["close"] > df["htf_trend"]
    else:
        df["htf_bull"] = True
        
    return df

ind_15m = {s: compute_indicators_df(klines_15m[s], klines_1h[s]) for s in SYMBOLS}
ind_1h = {s: compute_indicators_df(klines_1h[s], klines_4h[s]) for s in SYMBOLS}

def run_simulation(strategy_def, max_slots=2, margin=25.0, leverage=5):
    tf = strategy_def["timeframe"]
    datasets = ind_15m if tf == "15m" else ind_1h
    step_minutes = 15 if tf == "15m" else 60
    
    # Precompute signals for each symbol
    sym_sigs = {}
    for s in SYMBOLS:
        df = datasets[s]
        sig, sl_dist_ser, tp_dist_ser, be_mode = strategy_def["gen_signal"](df)
        sym_sigs[s] = {
            "df": df,
            "sig": sig,
            "sl_dist": sl_dist_dist if (sl_dist_dist := sl_dist_ser) is not None else df["atr"] * 1.5,
            "tp_dist": tp_dist_ser if tp_dist_ser is not None else df["atr"] * 3.0,
            "be_mode": be_mode
        }
        
    balance = 100.0
    peak_balance = 100.0
    max_dd = 0.0
    fee_rate = 0.0004
    
    active_positions = []
    closed_trades = []
    daily_pnl = {}
    prev_bar_ts = None
    
    for t in all_times_utc:
        # Round down to bar timeframe
        if tf == "15m":
            curr_bar_ts = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0)
        else:
            curr_bar_ts = t.replace(minute=0, second=0, microsecond=0)
            
        date_str = str(t)[:10]
        daily_pnl.setdefault(date_str, 0.0)
        
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
            be_type = pos["be_mode"]
            closed = False
            exit_p = curr_p
            reason = ""
            
            if d == 1: # LONG
                if curr_p > pos["peak_p"]:
                    pos["peak_p"] = curr_p
                gain_r = (curr_p - en_p) / sl_dist if sl_dist > 0 else 0
                gain_pct = (curr_p - en_p) / en_p
                
                if be_type == "ladder":
                    if gain_r >= 1.2 and pos["ladder_step"] < 1:
                        pos["sl_price"] = en_p + (0.5 * sl_dist)
                        pos["ladder_step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["ladder_step"] < 2:
                        pos["sl_price"] = en_p + (1.2 * sl_dist)
                        pos["ladder_step"] = 2
                elif be_type == "quick_be":
                    if not pos["be_locked"] and gain_pct >= 0.0040:
                        pos["sl_price"] = en_p * 1.0015
                        pos["be_locked"] = True
                elif be_type == "trailing":
                    if gain_pct >= 0.0080:
                        pos["be_locked"] = True
                        trail_target = pos["peak_p"] * (1.0 - 0.0035)
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
                
                if be_type == "ladder":
                    if gain_r >= 1.2 and pos["ladder_step"] < 1:
                        pos["sl_price"] = en_p - (0.5 * sl_dist)
                        pos["ladder_step"] = 1
                        pos["be_locked"] = True
                    elif gain_r >= 1.8 and pos["ladder_step"] < 2:
                        pos["sl_price"] = en_p - (1.2 * sl_dist)
                        pos["ladder_step"] = 2
                elif be_type == "quick_be":
                    if not pos["be_locked"] and gain_pct >= 0.0040:
                        pos["sl_price"] = en_p * (1.0 - 0.0015)
                        pos["be_locked"] = True
                elif be_type == "trailing":
                    if gain_pct >= 0.0080:
                        pos["be_locked"] = True
                        trail_target = pos["peak_p"] * (1.0 + 0.0035)
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
                    "gross_pnl": round(gross, 2),
                    "fees": round(fees, 2),
                    "net_pnl": round(net, 2),
                    "reason": reason
                })
            else:
                surviving.append(pos)
                
        active_positions = surviving
        
        # 2. Check for new entries on bar close
        if curr_bar_ts != prev_bar_ts:
            prev_bar_ts = curr_bar_ts
            eval_time = curr_bar_ts - pd.Timedelta(minutes=step_minutes)
            
            if len(active_positions) < max_slots:
                open_symbols = {p["symbol"] for p in active_positions}
                for s in SYMBOLS:
                    if s in open_symbols:
                        continue
                    if len(active_positions) >= max_slots:
                        break
                        
                    s_data = sym_sigs[s]
                    df_s = s_data["df"]
                    
                    if eval_time in df_s.index:
                        sig = s_data["sig"].loc[eval_time]
                        if sig != 0:
                            curr_tick_p = price_lookups[s].get(t)
                            if curr_tick_p is None:
                                continue
                                
                            sl_dist = s_data["sl_dist"].loc[eval_time]
                            tp_dist = s_data["tp_dist"].loc[eval_time]
                            if pd.isna(sl_dist) or sl_dist <= 0 or pd.isna(tp_dist) or tp_dist <= 0:
                                continue
                                
                            notional = margin * leverage
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
                                "be_mode": s_data["be_mode"]
                            }
                            active_positions.append(new_pos)
                            open_symbols.add(s)

    total_trades = len(closed_trades)
    if total_trades == 0:
        return {"name": strategy_def["name"], "net_pnl": 0.0, "total_trades": 0, "win_rate": 0, "profit_factor": 0, "max_dd_usd": 0, "fees": 0}
        
    wins = [t for t in closed_trades if t["net_pnl"] > 0]
    losses = [t for t in closed_trades if t["net_pnl"] < 0]
    bes = [t for t in closed_trades if t["reason"] == "BREAK_EVEN"]
    sls = [t for t in closed_trades if t["reason"] == "STOP_LOSS"]
    tps = [t for t in closed_trades if t["reason"] == "TAKE_PROFIT"]
    
    tot_win = sum(t["net_pnl"] for t in wins)
    tot_loss = abs(sum(t["net_pnl"] for t in losses))
    pf = round(tot_win / tot_loss, 2) if tot_loss > 0 else 999.0
    wr = round(len(wins) / total_trades * 100, 1)
    net = round(balance - 100.0, 2)
    tot_fees = round(sum(t["fees"] for t in closed_trades), 2)
    
    active_days = [v for k, v in daily_pnl.items() if v != 0]
    win_days = [v for v in active_days if v > 0]
    loss_days = [v for v in active_days if v < 0]
    
    return {
        "name": strategy_def["name"],
        "tf": tf,
        "net_pnl": net,
        "trades": total_trades,
        "win_rate": wr,
        "profit_factor": pf,
        "tp": len(tps),
        "be": len(bes),
        "sl": len(sls),
        "fees": tot_fees,
        "max_dd": round(max_dd, 2),
        "green_days": len(win_days),
        "red_days": len(loss_days)
    }

# STRATEGY DEFINITIONS TO EXPLORE
test_strategies = []

# S1: 15m Momentum Scalper (15m 9/21 EMA + 50 EMA trend + RSI + Quick Ladder)
def sig_15m_momentum(df):
    c = df["close"]
    fast = df["ema_9"]
    slow = df["ema_21"]
    trend = df["ema_50"]
    rsi = df["rsi"]
    atr = df["atr"]
    cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    
    buy = (c > trend) & cross_up & (rsi > 50) & (rsi < 68)
    sell = (c < trend) & cross_down & (rsi < 50) & (rsi > 32)
    
    sig = pd.Series(0, index=df.index)
    sig[buy] = 1
    sig[sell] = -1
    return sig, atr * 1.4, atr * 2.8, "ladder"

test_strategies.append({"name": "15m_EMA_Momentum_Ladder", "timeframe": "15m", "gen_signal": sig_15m_momentum})

# S2: 15m Bollinger Mean Reversion (Scalping choppy extremes)
def sig_15m_bb_meanrev(df):
    c = df["close"]
    low = df["low"]
    high = df["high"]
    bbl = df["bb_lower"]
    bbu = df["bb_upper"]
    rsi = df["rsi"]
    atr = df["atr"]
    adx = df["adx"]
    
    # Only when chop is high (ADX < 25)
    chop = adx < 25
    buy = chop & (low <= bbl) & (c > bbl) & (rsi < 35)
    sell = chop & (high >= bbu) & (c < bbu) & (rsi > 65)
    
    sig = pd.Series(0, index=df.index)
    sig[buy] = 1
    sig[sell] = -1
    return sig, atr * 1.0, atr * 1.6, "quick_be"

test_strategies.append({"name": "15m_BB_MeanReversion_Chop", "timeframe": "15m", "gen_signal": sig_15m_bb_meanrev})

# S3: 15m MTF Trend Pullback (1H 50 EMA Trend + 15m 21 EMA Retest)
def sig_15m_mtf_pullback(df):
    c = df["close"]
    ema9 = df["ema_9"]
    ema21 = df["ema_21"]
    htf_bull = df["htf_bull"]
    rsi = df["rsi"]
    atr = df["atr"]
    
    # In 1H bull trend, price dips to 15m 21 EMA then closes back above 9 EMA
    buy = htf_bull & (df["low"].rolling(3).min() <= ema21) & (c > ema9) & (c.shift(1) <= ema9.shift(1)) & (rsi > 45) & (rsi < 62)
    sell = (~htf_bull) & (df["high"].rolling(3).max() >= ema21) & (c < ema9) & (c.shift(1) >= ema9.shift(1)) & (rsi < 55) & (rsi > 38)
    
    sig = pd.Series(0, index=df.index)
    sig[buy] = 1
    sig[sell] = -1
    return sig, atr * 1.2, atr * 2.6, "ladder"

test_strategies.append({"name": "15m_MTF_Pullback_Sniper", "timeframe": "15m", "gen_signal": sig_15m_mtf_pullback})

# S4: 1H RSI Extreme Pullback with 200 EMA Regime
def sig_1h_rsi_pullback(df):
    c = df["close"]
    ema200 = df["ema_200"]
    rsi = df["rsi"]
    atr = df["atr"]
    ema9 = df["ema_9"]
    
    # In 1H Bull regime (c > 200 EMA), buy oversold dip (RSI < 42, then crosses above 45)
    buy = (c > ema200) & (rsi > 44) & (rsi.shift(1) <= 44) & (rsi.rolling(4).min() < 40)
    sell = (c < ema200) & (rsi < 56) & (rsi.shift(1) >= 56) & (rsi.rolling(4).max() > 60)
    
    sig = pd.Series(0, index=df.index)
    sig[buy] = 1
    sig[sell] = -1
    return sig, atr * 1.4, atr * 2.8, "ladder"

test_strategies.append({"name": "1H_RSI_Oversold_Pullback", "timeframe": "1h", "gen_signal": sig_1h_rsi_pullback})

# S5: 1H Dual-Filter EMA Momentum (1H 9/21 cross + 200 EMA + ADX > 20 + Vol > 0.9x + 2.4R TP)
def sig_1h_adx_momentum(df):
    c = df["close"]
    fast = df["ema_9"]
    slow = df["ema_21"]
    trend = df["ema_200"]
    rsi = df["rsi"]
    atr = df["atr"]
    adx = df["adx"]
    vol = df["vol_ratio"]
    plus_di = df["plus_di"]
    minus_di = df["minus_di"]
    
    cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    
    buy = (c > trend) & cross_up & (adx > 18) & (plus_di > minus_di) & (rsi > 46) & (rsi < 66) & (vol > 0.8)
    sell = (c < trend) & cross_down & (adx > 18) & (minus_di > plus_di) & (rsi < 54) & (rsi > 34) & (vol > 0.8)
    
    sig = pd.Series(0, index=df.index)
    sig[buy] = 1
    sig[sell] = -1
    return sig, atr * 1.5, atr * 2.5, "ladder"

test_strategies.append({"name": "1H_Optimized_ADX_Momentum", "timeframe": "1h", "gen_signal": sig_1h_adx_momentum})

# S6: 15m Adaptive Trend/Range Engine
def sig_15m_adaptive(df):
    c = df["close"]
    fast = df["ema_9"]
    slow = df["ema_21"]
    trend = df["ema_50"]
    rsi = df["rsi"]
    atr = df["atr"]
    adx = df["adx"]
    bbl = df["bb_lower"]
    bbu = df["bb_upper"]
    
    cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    
    # Trend mode: ADX >= 22
    t_buy = (adx >= 22) & (c > trend) & cross_up & (rsi > 48) & (rsi < 66)
    t_sell = (adx >= 22) & (c < trend) & cross_down & (rsi < 52) & (rsi > 34)
    
    # Range mode: ADX < 22
    r_buy = (adx < 22) & (df["low"] <= bbl) & (c > bbl) & (rsi < 35)
    r_sell = (adx < 22) & (df["high"] >= bbu) & (c < bbu) & (rsi > 65)
    
    sig = pd.Series(0, index=df.index)
    sig[t_buy | r_buy] = 1
    sig[t_sell | r_sell] = -1
    
    sl_dist = atr * 1.2
    tp_dist = atr * 2.2
    return sig, sl_dist, tp_dist, "ladder"

test_strategies.append({"name": "15m_Adaptive_Trend_Range", "timeframe": "15m", "gen_signal": sig_15m_adaptive})

# Run all explorations
print("\n--- Running Multi-Strategy Explorations on October Live Ticks ---")
results = []
for strat in test_strategies:
    t0 = time.time()
    res = run_simulation(strat, max_slots=2)
    el = time.time() - t0
    print(f"[{res['name']}] Net PnL: ${res['net_pnl']:+.2f} | WR: {res['win_rate']}% | Trades: {res['trades']} | PF: {res['profit_factor']} | Max DD: ${res['max_dd']} ({el:.1f}s)")
    results.append(res)

print("\n" + "=" * 92)
print("              EXPLORATION RESULTS: OCTOBER LIVE TICK PERFORMANCE")
print("=" * 92)
print(f"{'Strategy Name':<28} | {'TF':<4} | {'Net PnL':<10} | {'Win Rate':<10} | {'Trades':<8} | {'PF':<6} | {'Max DD':<9} | {'Fees':<7}")
print("-" * 92)
for r in sorted(results, key=lambda x: x["net_pnl"], reverse=True):
    print(f"{r['name']:<28} | {r['tf']:<4} | ${r['net_pnl']:<+9.2f} | {r['win_rate']:<9.1f}% | {r['trades']:<8} | {r['profit_factor']:<6} | ${r['max_dd']:<8.2f} | ${r['fees']:<6.2f}")
print("=" * 92)

with open("exploration_october_results.json", "w") as f:
    json.dump(results, f, indent=2)
