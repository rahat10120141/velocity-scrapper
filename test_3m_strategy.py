import pandas as pd
import numpy as np
from binance_client import BinanceClient
from indicators import compute_all_indicators

client = BinanceClient(mode="FUTURES")

def test_pair(symbol="SOLUSDT", interval="3m", limit=2000):
    print(f"Testing {symbol} on {interval} timeframe...")
    df = client.fetch_klines(symbol, interval=interval, limit=limit)
    
    # 1. EMA 9, 21, 50
    c = df["close"]
    df["ema_fast"] = c.ewm(span=9, adjust=False).mean()
    df["ema_slow"] = c.ewm(span=21, adjust=False).mean()
    df["ema_trend"] = c.ewm(span=50, adjust=False).mean()
    
    # 2. RSI & StochRSI
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
    
    # 3. Volume
    df["vol_ma"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / (df["vol_ma"] + 1e-9)
    
    # Simulate
    notional = 125.0
    fee_rate = 0.0004 * 2
    
    results = []
    
    for tp_pct in [0.006, 0.008, 0.010]:
        for sl_pct in [0.004, 0.005]:
            trades = []
            in_trade = False
            side = None
            ep = 0.0
            tp = 0.0
            sl = 0.0
            dur = 0
            
            for i in range(50, len(df)):
                row = df.iloc[i]
                prev = df.iloc[i-1]
                close_p = row["close"]
                high_p = row["high"]
                low_p = row["low"]
                open_p = row["open"]
                
                if in_trade:
                    dur += 1
                    if side == "BUY":
                        if high_p >= tp:
                            net = (tp - ep) / ep * notional - (notional * fee_rate)
                            trades.append(net)
                            in_trade = False
                        elif low_p <= sl:
                            net = (sl - ep) / ep * notional - (notional * fee_rate)
                            trades.append(net)
                            in_trade = False
                        elif dur >= 15: # 45 minutes
                            net = (close_p - ep) / ep * notional - (notional * fee_rate)
                            trades.append(net)
                            in_trade = False
                    elif side == "SELL":
                        if low_p <= tp:
                            net = (ep - tp) / ep * notional - (notional * fee_rate)
                            trades.append(net)
                            in_trade = False
                        elif high_p >= sl:
                            net = (ep - sl) / ep * notional - (notional * fee_rate)
                            trades.append(net)
                            in_trade = False
                        elif dur >= 15:
                            net = (ep - close_p) / ep * notional - (notional * fee_rate)
                            trades.append(net)
                            in_trade = False
                    continue
                
                # Signal Generation:
                # Bullish: Trend is UP (EMA 21 > EMA 50), Price pulls back near EMA 21, StochRSI crosses UP from < 30
                ema_bull = (row["ema_slow"] > row["ema_trend"]) and (close_p > row["ema_trend"])
                ema_bear = (row["ema_slow"] < row["ema_trend"]) and (close_p < row["ema_trend"])
                
                stoch_cross_up = (row["stoch_k"] > row["stoch_d"]) and (prev["stoch_k"] <= prev["stoch_d"]) and (row["stoch_k"] <= 35)
                stoch_cross_down = (row["stoch_k"] < row["stoch_d"]) and (prev["stoch_k"] >= prev["stoch_d"]) and (row["stoch_k"] >= 65)
                
                if ema_bull and stoch_cross_up and (close_p > open_p) and (row["vol_ratio"] >= 1.0):
                    in_trade = True
                    side = "BUY"
                    ep = close_p
                    tp = ep * (1 + tp_pct)
                    sl = ep * (1 - sl_pct)
                    dur = 0
                elif ema_bear and stoch_cross_down and (close_p < open_p) and (row["vol_ratio"] >= 1.0):
                    in_trade = True
                    side = "SELL"
                    ep = close_p
                    tp = ep * (1 - tp_pct)
                    sl = ep * (1 + sl_pct)
                    dur = 0
            
            if trades:
                wins = [t for t in trades if t > 0]
                total_pnl = sum(trades)
                wr = len(wins) / len(trades) * 100
                days = (df.index[-1] - df.index[0]).total_seconds() / 86400
                daily = total_pnl / max(1, days)
                results.append({
                    "tp": tp_pct * 100,
                    "sl": sl_pct * 100,
                    "trades": len(trades),
                    "wr": wr,
                    "net_pnl": total_pnl,
                    "daily": daily
                })
    
    rdf = pd.DataFrame(results)
    if not rdf.empty:
        print(rdf.sort_values(by="net_pnl", ascending=False).head(10).to_string(index=False))

if __name__ == "__main__":
    test_pair("SOLUSDT", "3m", 2500)
    test_pair("BTCUSDT", "3m", 2500)
