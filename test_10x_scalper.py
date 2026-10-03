import pandas as pd
import numpy as np
from binance_client import BinanceClient

client = BinanceClient(mode="FUTURES")

def test_10x_scalper(symbol="SOLUSDT", interval="3m", total_bars=3000):
    df = client.fetch_klines(symbol, interval=interval, limit=total_bars)
    c, h, l, o = df["close"], df["high"], df["low"], df["open"]
    
    # 1. Trend Filter: EMA 50 & EMA 200
    df["ema_trend"] = c.ewm(span=100, adjust=False).mean()
    df["ema_fast"] = c.ewm(span=9, adjust=False).mean()
    df["ema_slow"] = c.ewm(span=21, adjust=False).mean()
    
    # 2. StochRSI
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    min_rsi = rsi.rolling(14).min()
    max_rsi = rsi.rolling(14).max()
    stoch = ((rsi - min_rsi) / (max_rsi - min_rsi + 1e-9)) * 100
    df["stoch_k"] = stoch.rolling(3).mean()
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()
    
    # 3. Volume filter
    df["vol_ma"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / (df["vol_ma"] + 1e-9)
    
    # 10x Leverage Simulation on $25 Margin ($250 Notional Position)
    notional = 250.0
    fee_rate = 0.0004 # 0.04% per trade (0.08% roundtrip = $0.20 per trade)
    
    for tp_p in [0.008, 0.010, 0.012]: # 0.8%, 1.0%, 1.2%
        for sl_p in [0.0045, 0.0050]:  # 0.45%, 0.50%
            trades = []
            in_pos = False
            direction = 0
            ep = 0.0
            tp = 0.0
            sl = 0.0
            peak = 0.0
            be_active = False
            dur = 0
            
            for i in range(100, len(df)):
                row = df.iloc[i]
                prev = df.iloc[i-1]
                curr_c, curr_h, curr_l, curr_o = row["close"], row["high"], row["low"], row["open"]
                
                if in_pos:
                    dur += 1
                    closed = False
                    exit_p = curr_c
                    reason = ""
                    
                    if direction == 1:
                        if curr_h > peak:
                            peak = curr_h
                        # Break-Even Trigger at +0.40% profit
                        if not be_active and (peak - ep) / ep >= 0.0040:
                            sl = ep * 1.0012 # Lock fee
                            be_active = True
                            
                        if curr_h >= tp:
                            exit_p = tp
                            reason = "TP"
                            closed = True
                        elif curr_l <= sl:
                            exit_p = sl
                            reason = "SL" if not be_active else "BE"
                            closed = True
                        elif dur >= 20: # 60 minutes time exit
                            exit_p = curr_c
                            reason = "TIME"
                            closed = True
                            
                        if closed:
                            gross = (exit_p - ep) / ep * notional
                            fees = notional * fee_rate * 2
                            net = gross - fees
                            trades.append((reason, net, dur))
                            in_pos = False
                            
                    elif direction == -1:
                        if curr_l < peak:
                            peak = curr_l
                        if not be_active and (ep - peak) / ep >= 0.0040:
                            sl = ep * 0.9988
                            be_active = True
                            
                        if curr_l <= tp:
                            exit_p = tp
                            reason = "TP"
                            closed = True
                        elif curr_h >= sl:
                            exit_p = sl
                            reason = "SL" if not be_active else "BE"
                            closed = True
                        elif dur >= 20:
                            exit_p = curr_c
                            reason = "TIME"
                            closed = True
                            
                        if closed:
                            gross = (ep - exit_p) / ep * notional
                            fees = notional * fee_rate * 2
                            net = gross - fees
                            trades.append((reason, net, dur))
                            in_pos = False
                            
                    continue
                
                # Signal:
                is_bull_trend = curr_c > row["ema_trend"] and row["ema_fast"] > row["ema_slow"]
                is_bear_trend = curr_c < row["ema_trend"] and row["ema_fast"] < row["ema_slow"]
                
                stoch_up = (row["stoch_k"] > row["stoch_d"]) and (prev["stoch_k"] <= prev["stoch_d"]) and (row["stoch_k"] <= 30)
                stoch_down = (row["stoch_k"] < row["stoch_d"]) and (prev["stoch_k"] >= prev["stoch_d"]) and (row["stoch_k"] >= 70)
                
                if is_bull_trend and stoch_up and (curr_c > curr_o) and (row["vol_ratio"] >= 0.9):
                    in_pos = True
                    direction = 1
                    ep = curr_c
                    tp = ep * (1 + tp_p)
                    sl = ep * (1 - sl_p)
                    peak = ep
                    be_active = False
                    dur = 0
                elif is_bear_trend and stoch_down and (curr_c < curr_o) and (row["vol_ratio"] >= 0.9):
                    in_pos = True
                    direction = -1
                    ep = curr_c
                    tp = ep * (1 - tp_p)
                    sl = ep * (1 + sl_p)
                    peak = ep
                    be_active = False
                    dur = 0
                    
            if trades:
                tdf = pd.DataFrame(trades, columns=["reason", "net", "dur"])
                wins = tdf[tdf["net"] > 0]
                losses = tdf[tdf["net"] <= 0]
                tot = len(tdf)
                net_pnl = tdf["net"].sum()
                gross_win = wins["net"].sum()
                gross_loss = abs(losses["net"].sum())
                pf = gross_win / (gross_loss + 1e-9)
                days = (df.index[-1] - df.index[0]).total_seconds() / 86400
                daily = net_pnl / max(1, days)
                wr = (len(wins) / tot) * 100
                print(f"TP {tp_p*100:.1f}% | SL {sl_p*100:.2f}% -> Trades: {tot:2d} ({tot/days:.1f}/d) | WinRate: {wr:.1f}% | Net$: {net_pnl:+.2f} | Daily: ${daily:+.2f}/day | PF: {pf:.2f} | AvgDur: {tdf['dur'].mean()*3:.1f}m")

if __name__ == "__main__":
    print("=================== 10X ISOLATED SCALPER BACKTEST ===================")
    for sym in ["SOLUSDT", "BTCUSDT", "ETHUSDT"]:
        print(f"\n--- {sym} (3m) ---")
        test_10x_scalper(sym, "3m", 3000)
