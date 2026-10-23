"""
Test Donchian 20/10 Breakout with 200 EMA Regime on October 3-23 Live Recorded Ticks
Ultra-fast precomputed dictionary lookups.
"""
import glob
import pandas as pd
import numpy as np
import time

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

t0 = time.time()
print("1. Loading October ticks...")
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

print(f"2. Loading 1h klines and precomputing channels...")
klines_1h = {s: pd.read_csv(f"data/klines/{s}_1h_2026.csv", index_col=0, parse_dates=True) for s in SYMBOLS}

h20_dict = {}
l20_dict = {}
h10_dict = {}
l10_dict = {}
ema_dict = {}
atr_dict = {}

for s in SYMBOLS:
    df = klines_1h[s]
    c, h, l = df["close"], df["high"], df["low"]
    ema200 = c.ewm(span=200, adjust=False).mean()
    high_20 = h.rolling(20).max().shift(1)
    low_20 = l.rolling(20).min().shift(1)
    low_10 = l.rolling(10).min().shift(1)
    high_10 = h.rolling(10).max().shift(1)
    
    prev_c = c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - prev_c).abs(), (l - prev_c).abs()))
    atr = tr.rolling(14).mean()
    
    h20_dict[s] = dict(zip(df.index, high_20))
    l20_dict[s] = dict(zip(df.index, low_20))
    h10_dict[s] = dict(zip(df.index, high_10))
    l10_dict[s] = dict(zip(df.index, low_10))
    ema_dict[s] = dict(zip(df.index, ema200))
    atr_dict[s] = dict(zip(df.index, atr))

print("3. Replaying October ticks (Oct 3 - Oct 23)...")
balance = 100.0
peak = 100.0
max_dd = 0.0
fee_rate = 0.0004
risk_usd = 3.0
max_slots = 3

active_positions = []
closed_trades = []
daily_pnl = {}
prev_h = None

for t in all_times_utc:
    curr_h = t.replace(minute=0, second=0, microsecond=0)
    date_str = str(t)[:10]
    daily_pnl.setdefault(date_str, 0.0)
    
    # Update channels once per hour
    if curr_h != prev_h:
        prev_h = curr_h
        eval_t = curr_h - pd.Timedelta(hours=1)
        for pos in active_positions:
            s = pos["symbol"]
            d = pos["direction"]
            if d == 1:
                pos["exit_level"] = l10_dict[s].get(eval_t, pos["exit_level"])
            else:
                pos["exit_level"] = h10_dict[s].get(eval_t, pos["exit_level"])

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
        q = pos["quantity"]
        exit_level = pos["exit_level"]
        closed = False
        exit_p = curr_p
        
        if d == 1:
            if curr_p <= pos["hard_sl"]:
                exit_p = pos["hard_sl"]
                closed = True
            elif curr_p <= exit_level:
                exit_p = curr_p
                closed = True
        else:
            if curr_p >= pos["hard_sl"]:
                exit_p = pos["hard_sl"]
                closed = True
            elif curr_p >= exit_level:
                exit_p = curr_p
                closed = True
                
        if closed:
            gross = (exit_p - en_p) * q if d == 1 else (en_p - exit_p) * q
            fees = (en_p * q + exit_p * q) * fee_rate
            net = gross - fees
            balance += net
            daily_pnl[date_str] += net
            if balance > peak:
                peak = balance
            dd = peak - balance
            if dd > max_dd:
                max_dd = dd
            closed_trades.append({"symbol": s, "net": net, "time": str(t)})
        else:
            surviving.append(pos)
            
    active_positions = surviving
    
    # 2. Check for new entries on tick
    if len(active_positions) < max_slots:
        open_syms = {p["symbol"] for p in active_positions}
        eval_t = curr_h - pd.Timedelta(hours=1)
        for s in SYMBOLS:
            if s in open_syms or len(active_positions) >= max_slots:
                continue
            curr_p = price_lookups[s].get(t)
            if curr_p is None:
                continue
            h20 = h20_dict[s].get(eval_t)
            l20 = l20_dict[s].get(eval_t)
            ema = ema_dict[s].get(eval_t)
            atr_v = atr_dict[s].get(eval_t)
            
            if h20 is None or l20 is None or ema is None or atr_v is None or atr_v <= 0:
                continue
                
            sig = 0
            if curr_p > h20 and curr_p > ema:
                sig = 1
            elif curr_p < l20 and curr_p < ema:
                sig = -1
                
            if sig != 0:
                sl_dist = 2.0 * atr_v
                pos_sz = risk_usd / sl_dist
                hard_sl = curr_p - sl_dist if sig == 1 else curr_p + sl_dist
                exit_l = l10_dict[s].get(eval_t, curr_p) if sig == 1 else h10_dict[s].get(eval_t, curr_p)
                active_positions.append({
                    "symbol": s,
                    "direction": sig,
                    "entry_price": curr_p,
                    "quantity": pos_sz,
                    "hard_sl": hard_sl,
                    "exit_level": exit_l
                })
                open_syms.add(s)

wins = [x for x in closed_trades if x["net"] > 0]
losses = [x for x in closed_trades if x["net"] < 0]
tot_net = round(balance - 100.0, 2)
wr = len(wins) / len(closed_trades) * 100 if len(closed_trades) > 0 else 0
gp = sum(x["net"] for x in wins)
gl = abs(sum(x["net"] for x in losses))
pf = round(gp / gl, 2) if gl > 0 else 999.0

# Daily breakdown
print(f"\n==========================================================================")
print(f"OCTOBER 3-23 LIVE RECORDED TICK REPLAY: DONCHIAN 20/10 + 200 EMA")
print(f"==========================================================================")
print(f"  Net Profit ($) : ${tot_net:+.2f} (+{tot_net:.1f}% gain in 20 days!)")
print(f"  Daily Average  : ${tot_net / 20:.2f} / day")
print(f"  Final Balance  : ${balance:.2f}")
print(f"  Total Trades   : {len(closed_trades)} ({len(closed_trades) / 20:.1f} trades/day)")
print(f"  Win Rate (%)   : {wr:.1f}% ({len(wins)} wins, {len(losses)} losses)")
print(f"  Profit Factor  : {pf:.2f} (Gross Win: ${gp:.2f}, Gross Loss: ${gl:.2f})")
print(f"  Max Drawdown   : ${max_dd:.2f} ({(max_dd / peak) * 100:.1f}%)")
print(f"  Elapsed Time   : {time.time() - t0:.1f}s")
print(f"==========================================================================")

print("\n--- Daily PnL Breakdown in October ---")
for d, pnl in sorted(daily_pnl.items()):
    if pnl != 0:
        bar = "🟢" if pnl > 0 else "🔴"
        print(f"  {d}: ${pnl:+.2f} {bar}")
