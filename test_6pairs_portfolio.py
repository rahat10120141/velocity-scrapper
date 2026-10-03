import urllib.request
import json
import time
import datetime
import pandas as pd
import numpy as np

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT"]

def fetch_klines(symbol, interval="1h", limit=1000):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "count", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore"
    ])
    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df.set_index("time", inplace=True)
    return df

def run_portfolio_backtest(interval="1h", limit=1500):
    print(f"\n==========================================================================")
    print(f"  MULTI-PAIR GUARDIAN PORTFOLIO AUDIT ({interval.upper()}) - 6 MAJOR CRYPTOS")
    print(f"  Symbols: {', '.join(SYMBOLS)}")
    print(f"==========================================================================")
    
    # 1. Fetch data for all 6 symbols
    datasets = {}
    for sym in SYMBOLS:
        print(f"Loading {interval} bars for {sym}...")
        df = fetch_klines(sym, interval=interval, limit=limit)
        
        c = df["close"]
        h = df["high"]
        l = df["low"]
        
        df["ema_fast"] = c.ewm(span=9, adjust=False).mean()
        df["ema_slow"] = c.ewm(span=21, adjust=False).mean()
        df["ema_trend"] = c.ewm(span=200, adjust=False).mean()
        
        c_prev = c.shift(1)
        tr = np.maximum(h - l, np.maximum(abs(h - c_prev), abs(l - c_prev)))
        df["atr"] = tr.rolling(14).mean()
        
        df["regime"] = 0
        df.loc[c > df["ema_trend"], "regime"] = 1
        df.loc[c < df["ema_trend"], "regime"] = -1
        
        fast = df["ema_fast"]
        slow = df["ema_slow"]
        buy_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        sell_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        
        df["signal"] = 0
        df.loc[(df["regime"] == 1) & buy_cross, "signal"] = 1
        df.loc[(df["regime"] == -1) & sell_cross, "signal"] = -1
        
        datasets[sym] = df

    # Find common timeline
    all_times = sorted(list(set.union(*[set(df.index[200:]) for df in datasets.values()])))
    print(f"Evaluating portfolio across {len(all_times)} time steps ({all_times[0]} to {all_times[-1]})...")

    # 2. Sequential Event-Driven Portfolio Simulation (Strict Rule: Max 1 active trade at a time)
    active_position = None
    closed_trades = []
    daily_pnl = {}
    risk_usd = 3.00 # $3.00 risk per trade
    fee_rate = 0.0004 # 0.04% per leg

    for current_time in all_times:
        date_key = current_time.strftime("%Y-%m-%d")
        if date_key not in daily_pnl:
            daily_pnl[date_key] = 0.0

        # Check Active Position
        if active_position is not None:
            sym = active_position["symbol"]
            df = datasets[sym]
            if current_time in df.index:
                row = df.loc[current_time]
                curr_c, curr_h, curr_l = row["close"], row["high"], row["low"]
                
                direction = active_position["direction"]
                entry_p = active_position["entry_price"]
                pos_size = active_position["pos_size"]
                closed = False
                exit_p = curr_c
                reason = ""
                
                if direction == 1:
                    # Break-Even check (+1.0R)
                    if not active_position["be_locked"] and curr_h >= active_position["be_trigger"]:
                        active_position["sl_price"] = entry_p * 1.0018
                        active_position["be_locked"] = True
                    # Check TP
                    if curr_h >= active_position["tp_price"]:
                        exit_p = active_position["tp_price"]
                        reason = "TAKE_PROFIT"
                        closed = True
                    # Check SL
                    elif curr_l <= active_position["sl_price"]:
                        exit_p = active_position["sl_price"]
                        reason = "BREAK_EVEN" if active_position["be_locked"] else "STOP_LOSS"
                        closed = True
                    if closed:
                        gross = (exit_p - entry_p) * pos_size
                        fees = (entry_p * pos_size) * fee_rate * 2
                        net = gross - fees
                elif direction == -1:
                    if not active_position["be_locked"] and curr_l <= active_position["be_trigger"]:
                        active_position["sl_price"] = entry_p * 0.9982
                        active_position["be_locked"] = True
                    if curr_l <= active_position["tp_price"]:
                        exit_p = active_position["tp_price"]
                        reason = "TAKE_PROFIT"
                        closed = True
                    elif curr_h >= active_position["sl_price"]:
                        exit_p = active_position["sl_price"]
                        reason = "BREAK_EVEN" if active_position["be_locked"] else "STOP_LOSS"
                        closed = True
                    if closed:
                        gross = (entry_p - exit_p) * pos_size
                        fees = (entry_p * pos_size) * fee_rate * 2
                        net = gross - fees
                        
                if closed:
                    dur_hours = round((current_time - active_position["entry_time"]).total_seconds() / 3600, 1)
                    daily_pnl[date_key] += net
                    closed_trades.append({
                        "symbol": sym,
                        "direction": "LONG" if direction == 1 else "SHORT",
                        "entry_time": active_position["entry_time"],
                        "exit_time": current_time,
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "gross_pnl": round(gross, 2),
                        "fees": round(fees, 2),
                        "net_pnl": round(net, 2),
                        "duration_h": dur_hours,
                        "reason": reason
                    })
                    active_position = None

        # Check for new entry signal across all 6 symbols
        if active_position is None:
            # Check if daily target was reached today
            if daily_pnl.get(date_key, 0.0) >= 3.00:
                continue # Daily Profit Lock!

            for sym in SYMBOLS:
                df = datasets[sym]
                if current_time in df.index:
                    row = df.loc[current_time]
                    sig = row["signal"]
                    if sig != 0:
                        atr = row["atr"]
                        close_p = row["close"]
                        open_p = row["open"]
                        sl_dist = 1.0 * atr
                        if sl_dist <= 0: continue
                        
                        pos_size = risk_usd / sl_dist
                        if (close_p * pos_size) > 250.0:
                            pos_size = 250.0 / close_p
                            sl_dist = risk_usd / pos_size
                            
                        tp_dist = 2.2 * sl_dist
                        
                        active_position = {
                            "symbol": sym,
                            "direction": sig,
                            "entry_time": current_time,
                            "entry_price": close_p,
                            "pos_size": pos_size,
                            "sl_price": close_p - sl_dist if sig == 1 else close_p + sl_dist,
                            "tp_price": close_p + tp_dist if sig == 1 else close_p - tp_dist,
                            "be_trigger": close_p + sl_dist if sig == 1 else close_p - sl_dist,
                            "be_locked": False
                        }
                        break # Only 1 trade opened at a time!

    # Summary
    tdf = pd.DataFrame(closed_trades)
    if tdf.empty:
        print("No completed trades.")
        return

    wins = tdf[tdf["net_pnl"] > 0]
    losses = tdf[tdf["net_pnl"] <= 0]
    tot = len(tdf)
    win_rate = (len(wins) / tot) * 100
    gross_win = wins["net_pnl"].sum()
    gross_loss = abs(losses["net_pnl"].sum())
    pf = gross_win / (gross_loss + 1e-9)
    net_pnl = tdf["net_pnl"].sum()
    days = (all_times[-1] - all_times[0]).total_seconds() / 86400
    daily_avg = net_pnl / max(1, days)
    trades_per_day = tot / max(1, days)

    print("\n" + "=" * 70)
    print(f"  PORTFOLIO RESULTS ({interval.upper()}) - {days:.1f} DAYS")
    print("=" * 70)
    print(f"Total Completed Trades:      {tot} ({trades_per_day:.1f} trades/day)")
    print(f"Win Rate:                    {win_rate:.2f}% ({len(wins)} Wins / {len(losses)} Losses)")
    print(f"  - Full TP (2.2R) Hits:     {len(tdf[tdf['reason']=='TAKE_PROFIT'])}")
    print(f"  - Break-Even Saves:        {len(tdf[tdf['reason']=='BREAK_EVEN'])}")
    print(f"  - Stop-Loss Hits:          {len(tdf[tdf['reason']=='STOP_LOSS'])}")
    print(f"Gross Profit:                ${tdf['gross_pnl'].sum():+.2f}")
    print(f"Total Fees Paid:             ${tdf['fees'].sum():.2f}")
    print(f"Net Profit (After All Fees): ${net_pnl:+.2f} ({((100+net_pnl)-100):+.1f}% on $100)")
    print(f"Profit Factor (PF):          {pf:.2f}")
    print(f"Average Daily Net Profit:    ${daily_avg:+.2f} / day")
    print(f"Average Time in Trade:       {tdf['duration_h'].mean():.1f} hours")
    print("=" * 70)
    print("\nTrades per Symbol:")
    print(tdf["symbol"].value_counts().to_string())

if __name__ == "__main__":
    run_portfolio_backtest(interval="1h", limit=1500)
