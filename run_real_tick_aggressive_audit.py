"""
VELOCITY SCALPER: Empirical Real Sub-Second Tick Audit
Replays the 5-Minute Aggressive Quant Scalper through tens of millions of
authentic Binance sub-second ticks from BTCUSDT-aggTrades-2026-09.zip.
Models exact tick fills, Break-Even locks (+1.0R), fees, and Daily Circuit Breakers ($3 Target / $3 Loss).
"""
import zipfile
import datetime
import time
import os
import urllib.request
import urllib.parse
import json
import pandas as pd
import numpy as np

TICK_DATA_DIR = "/home/rahat/Documents/claude/tick_data"
ZIP_PATH_SEP = os.path.join(TICK_DATA_DIR, "BTCUSDT-aggTrades-2026-09.zip")
ZIP_PATH_JAN = os.path.join(TICK_DATA_DIR, "BTCUSDT-aggTrades-2026-01.zip")

def fetch_5m_bars(start_dt, end_dt):
    """Fetch 5m candlestick dataset from Binance Futures REST API."""
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    
    collected = []
    cur_start = start_ts
    headers = {"User-Agent": "Mozilla/5.0"}
    
    print(f"Fetching 5m bars from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}...")
    while cur_start < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&startTime={cur_start}&endTime={end_ts}&limit=1000"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            break
        collected.extend(data)
        cur_start = data[-1][0] + (300 * 1000) # +5 minutes
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
    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df.set_index("time", inplace=True)
    return df

def run_real_tick_audit(month_str="2026-09"):
    zip_path = ZIP_PATH_SEP if month_str == "2026-09" else ZIP_PATH_JAN
    if not os.path.exists(zip_path):
        print(f"Error: {zip_path} not found!")
        return

    year = int(month_str.split("-")[0])
    month = int(month_str.split("-")[1])
    
    # Warmup period 7 days before
    warmup_dt = datetime.datetime(year, month, 1, 0, 0) - datetime.timedelta(days=7)
    if month == 12:
        end_dt = datetime.datetime(year + 1, 1, 1, 0, 0)
    else:
        end_dt = datetime.datetime(year, month + 1, 1, 0, 0)

    # 1. Fetch 5m candles and compute indicators
    df_5m = fetch_5m_bars(warmup_dt, end_dt)
    c = df_5m["close"]
    h = df_5m["high"]
    l = df_5m["low"]
    o = df_5m["open"]
    
    # Strategy Indicator Setup (Velocity Scalper)
    df_5m["ema_fast"] = c.ewm(span=9, adjust=False).mean()
    df_5m["ema_slow"] = c.ewm(span=21, adjust=False).mean()
    df_5m["ema_trend"] = c.ewm(span=200, adjust=False).mean()
    
    # ATR 14
    c_prev = c.shift(1)
    tr = np.maximum(h - l, np.maximum(abs(h - c_prev), abs(l - c_prev)))
    df_5m["atr"] = tr.rolling(14).mean()
    
    # 200 EMA Regime
    df_5m["regime"] = 0
    df_5m.loc[c > df_5m["ema_trend"], "regime"] = 1   # Bullish
    df_5m.loc[c < df_5m["ema_trend"], "regime"] = -1  # Bearish
    
    # Crossover Signals
    fast = df_5m["ema_fast"]
    slow = df_5m["ema_slow"]
    buy_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    sell_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    
    df_5m["signal"] = 0
    df_5m.loc[(df_5m["regime"] == 1) & buy_cross, "signal"] = 1
    df_5m.loc[(df_5m["regime"] == -1) & sell_cross, "signal"] = -1

    # Extract all candidate signals for this target month
    signals = []
    for i in range(200, len(df_5m)):
        d = df_5m.index[i]
        sig = df_5m["signal"].iloc[i]
        if d.year == year and d.month == month and sig != 0:
            atr = df_5m["atr"].iloc[i]
            close_p = df_5m["close"].iloc[i]
            sl_dist = 1.0 * atr
            if sl_dist <= 0:
                continue
            
            # Risk $2.50 per trade, cap notional size at $250 (10x leverage on $25 margin)
            pos_size = 2.50 / sl_dist
            if (close_p * pos_size) > 250.0:
                pos_size = 250.0 / close_p
                sl_dist = 2.50 / pos_size

            tp_dist = 2.2 * sl_dist

            signals.append({
                "bar_time": d,
                # Entry happens at the open of the very next 5m bar (or close_time of current bar)
                "entry_ts": int((d + datetime.timedelta(minutes=5)).timestamp() * 1000),
                "direction": sig,
                "signal_close": close_p,
                "sl_dist": sl_dist,
                "tp_dist": tp_dist,
                "pos_size": pos_size,
                "initial_sl": close_p - sl_dist if sig == 1 else close_p + sl_dist,
                "tp_p": close_p + tp_dist if sig == 1 else close_p - tp_dist,
                "be_trigger": close_p + sl_dist if sig == 1 else close_p - sl_dist,
                "be_sl": close_p * (1.0 + 0.0018) if sig == 1 else close_p * (1.0 - 0.0018)
            })

    print(f"\nIdentified {len(signals)} 5-minute candidate signals in {month_str}.")
    print(f"Replaying against real tick archive: {os.path.basename(zip_path)}...")

    # 2. Replay against Real Sub-Second Ticks
    tick_trades = []
    daily_pnl_tracker = {}
    daily_breaker_tracker = {} # date -> "NORMAL" | "PROFIT_LOCKED" | "LOSS_LOCKED"
    
    t0 = time.time()
    processed_ticks = 0
    active_trade = None
    next_signal_idx = 0
    fee_rate = 0.0004 # 0.04% per trade leg

    csv_name = os.path.basename(zip_path).replace(".zip", ".csv")

    with zipfile.ZipFile(zip_path, "r") as z:
        with z.open(csv_name, "r") as f:
            header = f.readline().decode().strip().split(",")
            p_idx = header.index("price")
            t_idx = header.index("transact_time")
            
            for line in f:
                processed_ticks += 1
                parts = line.decode().strip().split(",")
                t_ms = int(parts[t_idx])
                price = float(parts[p_idx])
                
                dt_utc = datetime.datetime.fromtimestamp(t_ms / 1000, tz=datetime.timezone.utc)
                date_key = dt_utc.strftime("%Y-%m-%d")
                
                if date_key not in daily_pnl_tracker:
                    daily_pnl_tracker[date_key] = 0.0
                    daily_breaker_tracker[date_key] = "NORMAL"

                # Check if we should open a new trade
                if active_trade is None and next_signal_idx < len(signals):
                    sig = signals[next_signal_idx]
                    
                    # If this day is already circuit-broken (locked profit or locked loss), skip!
                    if daily_breaker_tracker.get(date_key) in ["PROFIT_LOCKED", "LOSS_LOCKED"]:
                        if t_ms >= sig["entry_ts"]:
                            next_signal_idx += 1
                            continue

                    if t_ms >= sig["entry_ts"]:
                        active_trade = dict(sig)
                        active_trade["entry_price"] = price # Exact real sub-second tick entry price!
                        active_trade["entry_time"] = dt_utc
                        active_trade["current_sl"] = price - sig["sl_dist"] if sig["direction"] == 1 else price + sig["sl_dist"]
                        active_trade["tp_price"] = price + sig["tp_dist"] if sig["direction"] == 1 else price - sig["tp_dist"]
                        active_trade["be_trigger_price"] = price + sig["sl_dist"] if sig["direction"] == 1 else price - sig["sl_dist"]
                        active_trade["be_sl_price"] = price * 1.0018 if sig["direction"] == 1 else price * 0.9982
                        active_trade["be_locked"] = False
                        next_signal_idx += 1

                # If trade is active, evaluate this exact tick!
                if active_trade is not None:
                    d = active_trade["direction"]
                    entry_p = active_trade["entry_price"]
                    pos_size = active_trade["pos_size"]
                    closed = False
                    exit_p = price
                    reason = ""

                    if d == 1: # LONG
                        # Check Break-Even trigger (+1.0R)
                        if not active_trade["be_locked"] and price >= active_trade["be_trigger_price"]:
                            active_trade["current_sl"] = active_trade["be_sl_price"]
                            active_trade["be_locked"] = True
                            
                        # Check TP hit
                        if price >= active_trade["tp_price"]:
                            exit_p = active_trade["tp_price"]
                            reason = "TAKE_PROFIT"
                            closed = True
                        # Check SL hit
                        elif price <= active_trade["current_sl"]:
                            exit_p = active_trade["current_sl"]
                            reason = "BREAK_EVEN" if active_trade["be_locked"] else "STOP_LOSS"
                            closed = True
                            
                        if closed:
                            gross = (exit_p - entry_p) * pos_size
                            fees = (entry_p * pos_size) * fee_rate * 2
                            net = gross - fees
                            
                    elif d == -1: # SHORT
                        # Check Break-Even trigger
                        if not active_trade["be_locked"] and price <= active_trade["be_trigger_price"]:
                            active_trade["current_sl"] = active_trade["be_sl_price"]
                            active_trade["be_locked"] = True
                            
                        if price <= active_trade["tp_price"]:
                            exit_p = active_trade["tp_price"]
                            reason = "TAKE_PROFIT"
                            closed = True
                        elif price >= active_trade["current_sl"]:
                            exit_p = active_trade["current_sl"]
                            reason = "BREAK_EVEN" if active_trade["be_locked"] else "STOP_LOSS"
                            closed = True
                            
                        if closed:
                            gross = (entry_p - exit_p) * pos_size
                            fees = (entry_p * pos_size) * fee_rate * 2
                            net = gross - fees

                    if closed:
                        dur_mins = round((dt_utc - active_trade["entry_time"]).total_seconds() / 60, 1)
                        daily_pnl_tracker[date_key] += net
                        
                        # Evaluate Daily Circuit Breakers
                        day_net = daily_pnl_tracker[date_key]
                        if day_net >= 3.00:
                            daily_breaker_tracker[date_key] = "PROFIT_LOCKED"
                        elif day_net <= -3.00:
                            daily_breaker_tracker[date_key] = "LOSS_LOCKED"

                        tick_trades.append({
                            "entry_time": active_trade["entry_time"].strftime("%Y-%m-%d %H:%M"),
                            "exit_time": dt_utc.strftime("%Y-%m-%d %H:%M"),
                            "direction": "LONG" if d == 1 else "SHORT",
                            "entry_price": round(entry_p, 2),
                            "exit_price": round(exit_p, 2),
                            "gross_pnl": round(gross, 2),
                            "fees": round(fees, 2),
                            "net_pnl": round(net, 2),
                            "duration_m": dur_mins,
                            "reason": reason,
                            "date": date_key
                        })
                        active_trade = None

    elapsed = time.time() - t0
    print(f"\nReplayed {processed_ticks:,} real ticks in {elapsed:.1f}s ({processed_ticks/elapsed:,.0f} ticks/s)!")

    # 3. Compile Master Report
    tdf = pd.DataFrame(tick_trades)
    if tdf.empty:
        print("No completed trades.")
        return

    wins = tdf[tdf["net_pnl"] > 0]
    losses = tdf[tdf["net_pnl"] <= 0]
    tot_trades = len(tdf)
    win_rate = (len(wins) / tot_trades) * 100
    gross_profit = wins["net_pnl"].sum()
    gross_loss = abs(losses["net_pnl"].sum())
    net_profit = tdf["net_pnl"].sum()
    profit_factor = gross_profit / (gross_loss + 1e-9)
    days_active = len(daily_pnl_tracker)
    daily_avg = net_profit / max(1, days_active)

    tp_wins = len(tdf[tdf["reason"] == "TAKE_PROFIT"])
    be_wins = len(tdf[tdf["reason"] == "BREAK_EVEN"])
    sl_losses = len(tdf[tdf["reason"] == "STOP_LOSS"])

    print("\n" + "=" * 80)
    print(f"  VELOCITY SCALPER (5M): REAL SUB-SECOND TICK AUDIT ({month_str})")
    print("=" * 80)
    print(f"Total Authentic Sub-Second Ticks Processed: {processed_ticks:,}")
    print(f"Total Completed Trades:                      {tot_trades} ({tot_trades/days_active:.1f} trades/day)")
    print(f"Win Rate:                                    {win_rate:.2f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"  - Full Take-Profit (2.2R) Wins:            {tp_wins}")
    print(f"  - Break-Even (+0.18% Fee Protected) Wins:  {be_wins}")
    print(f"  - Hard Stop-Loss (-1.0 ATR) Losses:        {sl_losses}")
    print(f"Gross Profit:                                ${tdf['gross_pnl'].sum():+.2f}")
    print(f"Total Exchange Fees Paid:                    ${tdf['fees'].sum():.2f}")
    print(f"Net Profit (After All Fees):                 ${net_profit:+.2f} ({((100+net_profit)-100):+.1f}% on $100)")
    print(f"Profit Factor (PF):                          {profit_factor:.2f}")
    print(f"Average Daily Net Profit:                    ${daily_avg:+.2f} / day")
    print(f"Average Trade Duration:                      {tdf['duration_m'].mean():.1f} minutes")
    print("=" * 80)

    # Save Markdown Audit Report
    report_file = f"real_tick_audit_{month_str}.md"
    with open(report_file, "w") as rf:
        rf.write(f"""# ⚡ Velocity Scalper (5M): Real Sub-Second Tick Audit ({month_str})

> **Platform:** Binance Futures Authentic Sub-Second Tick Archive  
> **Raw Dataset File:** `{os.path.basename(zip_path)}`  
> **Total Authentic Sub-Second Ticks Processed:** **{processed_ticks:,} Ticks**  
> **Testing Engine:** Velocity Scalper (5M Dynamic Momentum Pullback + 200 EMA Regime)  
> **Account Base:** $100.00 | **Risk Model:** 10x Isolated ($25 Margin) | SL: 1.0 ATR | TP: 2.2R | BE Lock: +1.0R  
> **Circuit Breakers Active:** Daily Profit Cap: $3.00 | Daily Loss Limit: $3.00

---

## 1. Executive Performance Summary

| Performance Metric | Real Sub-Second Ticks ({month_str}) |
| :--- | :---: |
| **Total Authentic Ticks Evaluated** | **{processed_ticks:,} Ticks** |
| **Total Completed Trades** | **{tot_trades} Trades** ({tot_trades/days_active:.1f} trades/day) |
| **Winning Trades (Net > 0)** | **{len(wins)} Wins** |
| **Losing Trades (Net <= 0)** | **{len(losses)} Losses** |
| **True Win Rate (%)** | **{win_rate:.2f}%** |
| **Full Take-Profit (2.2R) Hits** | **{tp_wins} Trades** |
| **Break-Even (+0.18% Fee Lock) Saves** | **{be_wins} Trades** |
| **Stop-Loss Cuts** | **{sl_losses} Trades** |
| **Gross Profit ($)** | **${tdf['gross_pnl'].sum():+.2f}** |
| **Total Exchange Taker Fees Paid** | **${tdf['fees'].sum():.2f}** |
| **Net Profit ($ / %)** | **${net_profit:+.2f} ({((100+net_profit)-100):+.1f}%)** |
| **Profit Factor (PF)** | **{profit_factor:.2f}** |
| **Average Daily Profit** | **${daily_avg:+.2f} / day** |
| **Average Time in Trade** | **{tdf['duration_m'].mean():.1f} minutes** |

---

## 2. Daily PnL & Circuit Breaker Tracking

| Date | Day Net PnL | Cumulative Equity | Daily Breaker Status |
| :---: | :---: | :---: | :---: |
""")
        cum_equity = 100.0
        for d, pnl in sorted(daily_pnl_tracker.items()):
            cum_equity += pnl
            status = daily_breaker_tracker.get(d, "NORMAL")
            status_badge = "🎯 PROFIT LOCKED" if status == "PROFIT_LOCKED" else ("🛡️ LOSS HALT" if status == "LOSS_LOCKED" else "NORMAL")
            rf.write(f"| **{d}** | ${pnl:+.2f} | ${cum_equity:.2f} | {status_badge} |\n")

        rf.write(f"""
---

## 3. Trade-by-Trade Real Sub-Second Tick Log

| # | Entry Time | Dir | Entry ($) | Exit ($) | Net PnL ($) | Duration | Exit Reason |
| :-: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
""")
        for idx, row in tdf.iterrows():
            pnl_sign = "+" if row["net_pnl"] >= 0 else ""
            rf.write(f"| {idx+1} | {row['entry_time']} | {row['direction']} | ${row['entry_price']} | ${row['exit_price']} | {pnl_sign}${row['net_pnl']:.2f} | {row['duration_m']}m | {row['reason']} |\n")

    print(f"\nAudit Report generated: {report_file}")
    return tdf

if __name__ == "__main__":
    run_real_tick_audit("2026-09")
