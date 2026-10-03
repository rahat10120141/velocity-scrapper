import pandas as pd
import numpy as np
from binance_client import BinanceClient

client = BinanceClient(mode="FUTURES")

def test_liquidity_sweep(symbol="SOLUSDT", interval="1m", lookback=25):
    print(f"\n=================== LIQUIDITY SWEEP TEST: {symbol} ({interval}) ===================")
    df = client.fetch_klines(symbol, interval=interval, limit=3000)
    
    # Calculate rolling high and low of the previous N bars (excluding current bar)
    df["swing_high"] = df["high"].shift(1).rolling(window=lookback).max()
    df["swing_low"] = df["low"].shift(1).rolling(window=lookback).min()
    
    # Volume filter
    df["vol_ma"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / (df["vol_ma"] + 1e-9)
    
    notional = 125.0
    fee_rate = 0.0004 * 2 # 0.08%
    
    for rr in [1.5, 2.0, 2.5]:
        trades = []
        in_trade = False
        side = None
        ep = 0.0
        tp = 0.0
        sl = 0.0
        dur = 0
        
        for i in range(lookback + 5, len(df)):
            row = df.iloc[i]
            c, h, l, o = row["close"], row["high"], row["low"], row["open"]
            sh = row["swing_high"]
            sl_level = row["swing_low"]
            
            if in_trade:
                dur += 1
                if side == "BUY":
                    if h >= tp:
                        net = (tp - ep) / ep * notional - (notional * fee_rate)
                        trades.append(("TP", net, dur))
                        in_trade = False
                    elif l <= sl:
                        net = (sl - ep) / ep * notional - (notional * fee_rate)
                        trades.append(("SL", net, dur))
                        in_trade = False
                    elif dur >= 20: # Time exit
                        net = (c - ep) / ep * notional - (notional * fee_rate)
                        trades.append(("TIME", net, dur))
                        in_trade = False
                elif side == "SELL":
                    if l <= tp:
                        net = (ep - tp) / ep * notional - (notional * fee_rate)
                        trades.append(("TP", net, dur))
                        in_trade = False
                    elif h >= sl:
                        net = (ep - sl) / ep * notional - (notional * fee_rate)
                        trades.append(("SL", net, dur))
                        in_trade = False
                    elif dur >= 20:
                        net = (ep - c) / ep * notional - (notional * fee_rate)
                        trades.append(("TIME", net, dur))
                        in_trade = False
                continue
                
            # SFP / Liquidity Sweep Detection:
            # Bullish Sweep (Long): Price swept below swing_low, but closed back ABOVE swing_low (bullish hammer/rejection)
            bullish_sweep = (l < sl_level) and (c > sl_level) and (c > o)
            # Bearish Sweep (Short): Price swept above swing_high, but closed back BELOW swing_high (bearish shooting star/rejection)
            bearish_sweep = (h > sh) and (c < sh) and (c < o)
            
            if bullish_sweep:
                risk = (c - l) / c
                if 0.0020 <= risk <= 0.0060: # Valid risk range
                    in_trade = True
                    side = "BUY"
                    ep = c
                    sl = l * 0.9995 # Just below wick
                    tp = ep + ((ep - sl) * rr)
                    dur = 0
            elif bearish_sweep:
                risk = (h - c) / c
                if 0.0020 <= risk <= 0.0060:
                    in_trade = True
                    side = "SELL"
                    ep = c
                    sl = h * 1.0005 # Just above wick
                    tp = ep - ((sl - ep) * rr)
                    dur = 0

        if trades:
            tdf = pd.DataFrame(trades, columns=["reason", "net", "dur"])
            wins = tdf[tdf["net"] > 0]
            losses = tdf[tdf["net"] <= 0]
            total_pnl = tdf["net"].sum()
            wr = len(wins) / len(tdf) * 100
            pf = wins["net"].sum() / (abs(losses["net"].sum()) + 1e-9)
            days = (df.index[-1] - df.index[0]).total_seconds() / 86400
            daily = total_pnl / max(1, days)
            print(f"RR 1:{rr:.1f} | Trades: {len(tdf):2d} ({len(tdf)/days:.1f}/day) | WinRate: {wr:.1f}% | ProfitFactor: {pf:.2f} | Net: ${total_pnl:+.2f} | Daily: ${daily:+.2f}/day | AvgDur: {tdf['dur'].mean():.1f} bars")

if __name__ == "__main__":
    for sym in ["SOLUSDT", "BTCUSDT", "ETHUSDT"]:
        test_liquidity_sweep(sym, "1m", 25)
        test_liquidity_sweep(sym, "3m", 25)
