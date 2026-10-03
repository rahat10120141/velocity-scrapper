"""
VELOCITY SCALPER: Concurrent Positions Experiment
Compares Max Concurrent Trades = 1 vs 2 vs 3 across 6 Major Cryptos:
BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, DOGEUSDT, LINKUSDT
Account: $100 starting balance, 10x leverage, $25 margin per trade ($250 notional)
"""
import urllib.request
import json
import time
import datetime
import pandas as pd
import numpy as np

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT"]

def fetch_klines(symbol, interval="1h", limit=1500):
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

def run_simulation(datasets, all_times, max_concurrent=1, initial_balance=100.0, margin_per_trade=25.0, risk_usd=2.50):
    active_positions = [] # List of open position dicts
    closed_trades = []
    daily_pnl = {}
    balance = initial_balance
    peak_balance = initial_balance
    max_dd = 0.0
    fee_rate = 0.0004 # 0.04% per leg

    for current_time in all_times:
        date_key = current_time.strftime("%Y-%m-%d")
        if date_key not in daily_pnl:
            daily_pnl[date_key] = 0.0

        day_realized = daily_pnl[date_key]
        daily_target_hit = (day_realized >= 3.00)
        daily_loss_hit = (day_realized <= -3.00)

        # 1. Update Existing Active Positions
        still_active = []
        for pos in active_positions:
            sym = pos["symbol"]
            df = datasets[sym]
            if current_time in df.index:
                row = df.loc[current_time]
                curr_c, curr_h, curr_l = row["close"], row["high"], row["low"]
                direction = pos["direction"]
                entry_p = pos["entry_price"]
                pos_size = pos["pos_size"]
                closed = False
                exit_p = curr_c
                reason = ""

                if direction == 1: # LONG
                    # Break-Even (+1.0R)
                    if not pos["be_locked"] and curr_h >= pos["be_trigger"]:
                        pos["sl_price"] = entry_p * 1.0018
                        pos["be_locked"] = True
                    # TP
                    if curr_h >= pos["tp_price"]:
                        exit_p = pos["tp_price"]
                        reason = "TP_HIT"
                        closed = True
                    elif curr_l <= pos["sl_price"]:
                        exit_p = pos["sl_price"]
                        reason = "BE_EXIT" if pos["be_locked"] else "SL_HIT"
                        closed = True
                    if closed:
                        gross = (exit_p - entry_p) * pos_size
                        fees = (entry_p * pos_size + exit_p * pos_size) * fee_rate
                        net = gross - fees
                elif direction == -1: # SHORT
                    if not pos["be_locked"] and curr_l <= pos["be_trigger"]:
                        pos["sl_price"] = entry_p * (1 - 0.0018)
                        pos["be_locked"] = True
                    if curr_l <= pos["tp_price"]:
                        exit_p = pos["tp_price"]
                        reason = "TP_HIT"
                        closed = True
                    elif curr_h >= pos["sl_price"]:
                        exit_p = pos["sl_price"]
                        reason = "BE_EXIT" if pos["be_locked"] else "SL_HIT"
                        closed = True
                    if closed:
                        gross = (entry_p - exit_p) * pos_size
                        fees = (entry_p * pos_size + exit_p * pos_size) * fee_rate
                        net = gross - fees

                if closed:
                    balance += net
                    daily_pnl[date_key] += net
                    if balance > peak_balance:
                        peak_balance = balance
                    dd = peak_balance - balance
                    if dd > max_dd:
                        max_dd = dd

                    dur_hours = round((current_time - pos["entry_time"]).total_seconds() / 3600, 1)
                    closed_trades.append({
                        "symbol": sym,
                        "direction": "LONG" if direction == 1 else "SHORT",
                        "entry_time": pos["entry_time"],
                        "exit_time": current_time,
                        "duration_hours": dur_hours,
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "reason": reason,
                        "net_pnl": net,
                        "fees": fees,
                        "balance": balance
                    })
                else:
                    still_active.append(pos)
            else:
                still_active.append(pos)

        active_positions = still_active

        # 2. Check for New Entries across the 6 symbols
        # Only enter if circuit breakers not triggered and open positions < max_concurrent
        if not daily_target_hit and not daily_loss_hit and len(active_positions) < max_concurrent:
            open_symbols = {p["symbol"] for p in active_positions}
            
            # Check available free margin: need at least margin_per_trade free
            current_margin_used = len(active_positions) * margin_per_trade
            if balance - current_margin_used >= margin_per_trade:
                for sym in SYMBOLS:
                    if sym in open_symbols:
                        continue # Already in a trade on this symbol
                    if len(active_positions) >= max_concurrent:
                        break # Limit reached
                        
                    df = datasets[sym]
                    if current_time in df.index:
                        row = df.loc[current_time]
                        sig = row["signal"]
                        atr = row["atr"]
                        curr_c = row["close"]
                        
                        if sig != 0 and not np.isnan(atr) and atr > 0:
                            entry_p = curr_c
                            sl_dist = 1.0 * atr
                            tp_dist = 2.2 * sl_dist
                            pos_size = risk_usd / sl_dist
                            
                            # Max notional cap based on allocated margin ($25 at 10x = $250)
                            max_notional = margin_per_trade * 10
                            pos_size = min(pos_size, max_notional / entry_p)
                            
                            if sig == 1: # BUY
                                sl_p = entry_p - sl_dist
                                tp_p = entry_p + tp_dist
                                be_trig = entry_p + sl_dist # +1.0R
                            else: # SELL
                                sl_p = entry_p + sl_dist
                                tp_p = entry_p - tp_dist
                                be_trig = entry_p - sl_dist # +1.0R
                                
                            active_positions.append({
                                "symbol": sym,
                                "direction": int(sig),
                                "entry_time": current_time,
                                "entry_price": entry_p,
                                "sl_price": sl_p,
                                "tp_price": tp_p,
                                "be_trigger": be_trig,
                                "be_locked": False,
                                "pos_size": pos_size
                            })
                            open_symbols.add(sym)

    # Calculate statistics
    total_trades = len(closed_trades)
    if total_trades == 0:
        return None
        
    wins = [t for t in closed_trades if t["net_pnl"] > 0]
    losses = [t for t in closed_trades if t["net_pnl"] <= 0]
    win_rate = (len(wins) / total_trades) * 100
    
    total_net = sum(t["net_pnl"] for t in closed_trades)
    total_fees = sum(t["fees"] for t in closed_trades)
    gross_win = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else 999.0
    
    target_days = sum(1 for p in daily_pnl.values() if p >= 3.00)
    loss_days = sum(1 for p in daily_pnl.values() if p <= -3.00)
    active_days = sum(1 for p in daily_pnl.values() if p != 0)
    
    return {
        "max_concurrent": max_concurrent,
        "total_trades": total_trades,
        "trades_per_day": total_trades / max(1, active_days),
        "win_rate": win_rate,
        "wins": len(wins),
        "losses": len(losses),
        "final_balance": balance,
        "net_pnl": total_net,
        "roi_pct": ((balance - initial_balance) / initial_balance) * 100,
        "fees": total_fees,
        "profit_factor": pf,
        "max_drawdown": max_dd,
        "max_dd_pct": (max_dd / peak_balance) * 100,
        "target_days": target_days,
        "loss_days": loss_days,
        "active_days": active_days
    }

def main():
    print("Fetching 1500 1H bars for 6 crypto assets...")
    datasets = {}
    for sym in SYMBOLS:
        df = fetch_klines(sym, interval="1h", limit=1500)
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

    all_times = sorted(list(set.union(*[set(df.index[200:]) for df in datasets.values()])))
    days = (all_times[-1] - all_times[0]).total_seconds() / 86400
    print(f"Data ready: {len(all_times)} time steps spanning {days:.1f} days ({all_times[0]} to {all_times[-1]})\n")

    results = []
    for mc in [1, 2, 3]:
        print(f"Running simulation with MAX CONCURRENT TRADES = {mc}...")
        res = run_simulation(datasets, all_times, max_concurrent=mc)
        if res:
            results.append(res)

    print("\n" + "="*95)
    print("       EMPIRICAL COMPARISON: MAX 1 vs MAX 2 vs MAX 3 CONCURRENT POSITIONS")
    print("="*95)
    print(f"{'CONCURRENT':<11} | {'TRADES':<7} | {'TRADES/D':<9} | {'WIN RATE':<9} | {'NET PNL':<10} | {'FEES':<8} | {'PF':<6} | {'MAX DD':<11} | {'TARGET DAYS':<11}")
    print("-" * 95)
    for r in results:
        dd_str = f"${r['max_drawdown']:.2f} ({r['max_dd_pct']:.1f}%)"
        print(f"Max {r['max_concurrent']:<7} | {r['total_trades']:<7} | {r['trades_per_day']:<9.1f} | {r['win_rate']:<8.1f}% | ${r['net_pnl']:<+9.2f} | ${r['fees']:<7.2f} | {r['profit_factor']:<6.2f} | {dd_str:<11} | {r['target_days']:<11}")
    print("="*95 + "\n")

if __name__ == "__main__":
    main()
