"""
VELOCITY SCALPER: Full Year-to-Date 2026 Backtest (Jan 1, 2026 - Oct 9, 2026)
Compares:
  1. Old Baseline Strategy (The setup that was consistently losing)
  2. New Optimized Strategy (RSI Filter, 1.8 ATR SL, 2.2R TP, No DOGE, 2 Concurrent Slots)
"""
import urllib.request
import json
import datetime
import time
import pandas as pd
import numpy as np

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT", "DOGEUSDT"]

# Dates: Warmup from Dec 20, 2025 so 200 EMA is primed on Jan 1, 2026
warmup_dt = datetime.datetime(2025, 12, 20, 0, 0, tzinfo=datetime.timezone.utc)
sim_start_dt = datetime.datetime(2026, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
end_dt = datetime.datetime(2026, 10, 9, 12, 0, tzinfo=datetime.timezone.utc)

warmup_ts = int(warmup_dt.timestamp() * 1000)
end_ts = int(end_dt.timestamp() * 1000)

print(f"Fetching historical 1h bars from Binance Futures ({warmup_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')})...")

def fetch_historical_bars(symbol):
    collected = []
    cur_start = warmup_ts
    headers = {"User-Agent": "Mozilla/5.0"}
    
    while cur_start < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&startTime={cur_start}&endTime={end_ts}&limit=1000"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            break
        collected.extend(data)
        cur_start = data[-1][0] + (3600 * 1000)
        if len(data) < 1000:
            break
        time.sleep(0.04)
        
    df = pd.DataFrame(collected, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "count", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore"
    ])
    df.drop_duplicates(subset=["open_time"], inplace=True)
    df.sort_values("open_time", inplace=True)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df.set_index("time", inplace=True)
    return df

raw_dfs = {}
for s in SYMBOLS:
    df = fetch_historical_bars(s)
    raw_dfs[s] = df
    print(f"  {s}: {len(df):,} bars ({df.index[0]} to {df.index[-1]})")

print("All historical bars loaded successfully.\n")

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100.0 - (100.0 / (1.0 + rs))

def run_backtest_simulation(config_name, symbols, sl_mult=1.0, rr=2.2, use_rsi=False, be_mode="early_be", max_slots=3):
    datasets = {}
    for sym in symbols:
        df = raw_dfs[sym].copy()
        c = df["close"]
        h = df["high"]
        l = df["low"]
        
        df["ema_fast"] = c.ewm(span=9, adjust=False).mean()
        df["ema_slow"] = c.ewm(span=21, adjust=False).mean()
        df["ema_trend"] = c.ewm(span=200, adjust=False).mean()
        
        c_prev = c.shift(1)
        tr = np.maximum(h - l, np.maximum(abs(h - c_prev), abs(l - c_prev)))
        df["atr"] = tr.rolling(14).mean()
        df["rsi"] = calc_rsi(c, 14)
        
        df["regime"] = 0
        df.loc[c > df["ema_trend"], "regime"] = 1
        df.loc[c < df["ema_trend"], "regime"] = -1
        
        fast = df["ema_fast"]
        slow = df["ema_slow"]
        buy_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        sell_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        
        if use_rsi:
            buy_filter = (df["rsi"] < 68) & (df["rsi"] > 45)
            sell_filter = (df["rsi"] > 32) & (df["rsi"] < 55)
        else:
            buy_filter = True
            sell_filter = True
            
        df["signal"] = 0
        df.loc[(df["regime"] == 1) & buy_cross & buy_filter, "signal"] = 1
        df.loc[(df["regime"] == -1) & sell_cross & sell_filter, "signal"] = -1
        datasets[sym] = df

    all_times = sorted(list(set.union(*[set(df.index) for df in datasets.values()])))
    sim_times = [t for t in all_times if t >= sim_start_dt]
    
    active_positions = []
    closed_trades = []
    daily_pnl = {}
    fee_rate = 0.0004
    margin = 25.0
    leverage = 5
    notional = margin * leverage # $125 notional position
    risk_usd = 2.50
    
    peak_equity = 100.0
    max_dd_dollars = 0.0
    current_equity = 100.0
    
    for t in sim_times:
        date_str = str(t)[:10]
        daily_pnl.setdefault(date_str, 0.0)
        
        # 1. Manage Active Positions
        surviving = []
        for pos in active_positions:
            sym = pos["symbol"]
            df = datasets[sym]
            if t not in df.index:
                surviving.append(pos)
                continue
            row = df.loc[t]
            curr_c, curr_h, curr_l = row["close"], row["high"], row["low"]
            d = pos["direction"]
            en_p = pos["entry_price"]
            pos_size = pos["pos_size"]
            sl_dist = pos["sl_dist"]
            closed = False
            exit_p = curr_c
            reason = ""
            
            if d == 1:
                gain_r = (curr_h - en_p) / sl_dist if sl_dist > 0 else 0
                gain_pct = (curr_h - en_p) / en_p
                
                if be_mode == "early_be":
                    if not pos["be_locked"] and gain_pct >= 0.0025:
                        pos["sl_price"] = en_p * 1.0010
                        pos["be_locked"] = True
                elif be_mode == "runner_1r":
                    if not pos["be_locked"] and gain_r >= 1.0:
                        pos["sl_price"] = en_p * 1.0018
                        pos["be_locked"] = True
                        
                if curr_h >= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif curr_l <= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    reason = "BREAK_EVEN" if pos.get("be_locked") and exit_p >= en_p else "STOP_LOSS"
                    closed = True
                    
                if closed:
                    gross = (exit_p - en_p) * pos_size
                    fees = (en_p * pos_size + exit_p * pos_size) * fee_rate
                    net = gross - fees
            elif d == -1:
                gain_r = (en_p - curr_l) / sl_dist if sl_dist > 0 else 0
                gain_pct = (en_p - curr_l) / en_p
                
                if be_mode == "early_be":
                    if not pos["be_locked"] and gain_pct >= 0.0025:
                        pos["sl_price"] = en_p * (1.0 - 0.0010)
                        pos["be_locked"] = True
                elif be_mode == "runner_1r":
                    if not pos["be_locked"] and gain_r >= 1.0:
                        pos["sl_price"] = en_p * (1.0 - 0.0018)
                        pos["be_locked"] = True
                        
                if curr_l <= pos["tp_price"]:
                    exit_p = pos["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif curr_h >= pos["sl_price"]:
                    exit_p = pos["sl_price"]
                    reason = "BREAK_EVEN" if pos.get("be_locked") and exit_p <= en_p else "STOP_LOSS"
                    closed = True
                    
                if closed:
                    gross = (en_p - exit_p) * pos_size
                    fees = (en_p * pos_size + exit_p * pos_size) * fee_rate
                    net = gross - fees
                    
            if closed:
                daily_pnl[date_str] += net
                current_equity += net
                if current_equity > peak_equity:
                    peak_equity = current_equity
                dd = peak_equity - current_equity
                if dd > max_dd_dollars:
                    max_dd_dollars = dd
                    
                closed_trades.append({
                    "time": t,
                    "month": str(t)[:7],
                    "symbol": sym,
                    "direction": "LONG" if d == 1 else "SHORT",
                    "gross_pnl": gross,
                    "fees": fees,
                    "net_pnl": net,
                    "reason": reason
                })
            else:
                surviving.append(pos)
                
        active_positions = surviving
        
        # 2. Check for New Entries
        if len(active_positions) < max_slots:
            open_symbols = {p["symbol"] for p in active_positions}
            for sym in symbols:
                if sym in open_symbols:
                    continue
                if len(active_positions) >= max_slots:
                    break
                df = datasets[sym]
                if t in df.index:
                    row = df.loc[t]
                    sig = row["signal"]
                    if sig != 0 and row["atr"] > 0:
                        close_p = row["close"]
                        sl_dist = sl_mult * row["atr"]
                        if sl_dist <= 0: continue
                        pos_size = notional / close_p
                        tp_dist = rr * sl_dist
                        
                        active_positions.append({
                            "symbol": sym,
                            "direction": sig,
                            "entry_price": close_p,
                            "pos_size": pos_size,
                            "sl_dist": sl_dist,
                            "sl_price": close_p - sl_dist if sig == 1 else close_p + sl_dist,
                            "tp_price": close_p + tp_dist if sig == 1 else close_p - tp_dist,
                            "be_locked": False
                        })

    tdf = pd.DataFrame(closed_trades)
    return tdf, max_dd_dollars

print("Running Backtest 1: OLD BASELINE STRATEGY (Jan 1, 2026 - Oct 9, 2026)...")
old_tdf, old_dd = run_backtest_simulation(
    "Old Baseline",
    SYMBOLS,
    sl_mult=1.0,
    rr=2.2,
    use_rsi=False,
    be_mode="early_be",
    max_slots=3
)

print("Running Backtest 2: NEW OPTIMIZED STRATEGY (Jan 1, 2026 - Oct 9, 2026)...")
new_tdf, new_dd = run_backtest_simulation(
    "New Optimized",
    [s for s in SYMBOLS if s != "DOGEUSDT"],
    sl_mult=1.8,
    rr=2.2,
    use_rsi=True,
    be_mode="none",
    max_slots=2
)

# Print Summary Results
def print_report(name, tdf, max_dd):
    wins = tdf[tdf["net_pnl"] > 0]
    losses = tdf[tdf["net_pnl"] <= 0]
    net_pnl = tdf["net_pnl"].sum()
    gross_pnl = tdf["gross_pnl"].sum()
    fees = tdf["fees"].sum()
    gw = wins["net_pnl"].sum() if not wins.empty else 0.0
    gl = abs(losses["net_pnl"].sum()) if not losses.empty else 1e-9
    pf = gw / gl
    wr = len(wins) / len(tdf) * 100 if len(tdf) > 0 else 0
    tp_c = len(tdf[tdf["reason"] == "TAKE_PROFIT"])
    be_c = len(tdf[tdf["reason"] == "BREAK_EVEN"])
    sl_c = len(tdf[tdf["reason"] == "STOP_LOSS"])
    
    print("\n" + "=" * 78)
    print(f"  {name.upper()}")
    print("=" * 78)
    print(f"  Total Trades:           {len(tdf):4d} ({len(tdf)/282:.2f} trades/day)")
    print(f"  Wins / Losses:          {len(wins)} Wins / {len(losses)} Losses")
    print(f"  Win Rate:               {wr:5.1f}%")
    print(f"  Take Profit Hits:       {tp_c:4d}")
    print(f"  Break-Even Saves:       {be_c:4d}")
    print(f"  Stop Loss Hits:         {sl_c:4d}")
    print(f"  Gross Profit:           ${gross_pnl:+7.2f}")
    print(f"  Exchange Fees Paid:     ${fees:7.2f}")
    print(f"  Net Realized PnL:       ${net_pnl:+7.2f} ({((100+net_pnl)-100):+5.1f}% on $100)")
    print(f"  Final Account Balance:  ${100.0 + net_pnl:7.2f}")
    print(f"  Profit Factor (PF):     {pf:7.2f}")
    print(f"  Max Drawdown:           ${max_dd:7.2f} ({max_dd/100*100:4.1f}%)")
    print("-" * 78)
    print("  Monthly Breakdown (Net PnL):")
    monthly = tdf.groupby("month")["net_pnl"].agg(["count", "sum"])
    monthly.columns = ["Trades", "Net PnL ($)"]
    for m, r in monthly.iterrows():
        pnl_val = r["Net PnL ($)"]
        sign = "+" if pnl_val > 0 else ""
        icon = "🟢" if pnl_val > 0 else "🔴"
        print(f"    {m}: {int(r['Trades']):2d} trades | Net: {sign}${pnl_val:6.2f} {icon}")
    print("-" * 78)
    print("  Symbol Breakdown (Net PnL):")
    by_s = tdf.groupby("symbol")["net_pnl"].agg(["count", "sum"])
    by_s.columns = ["Trades", "Net PnL ($)"]
    for sym, r in by_s.iterrows():
        pnl_val = r["Net PnL ($)"]
        sign = "+" if pnl_val > 0 else ""
        print(f"    {sym:8}: {int(r['Trades']):2d} trades | Net: {sign}${pnl_val:6.2f}")
    print("=" * 78 + "\n")

print_report("Old Baseline Strategy (Jan 1 - Oct 9, 2026)", old_tdf, old_dd)
print_report("New Optimized Strategy (Jan 1 - Oct 9, 2026)", new_tdf, new_dd)
