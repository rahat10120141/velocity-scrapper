import pandas as pd
import numpy as np
from binance_client import BinanceClient

client = BinanceClient(mode="FUTURES")

def test_guardian(symbol="SOLUSDT", interval="5m", total_bars=3000):
    df = client.fetch_klines(symbol, interval=interval, limit=total_bars)
    c = df["close"]
    h = df["high"]
    l = df["low"]
    o = df["open"]
    
    # Indicators
    df["ema_fast"] = c.ewm(span=9, adjust=False).mean()
    df["ema_slow"] = c.ewm(span=21, adjust=False).mean()
    df["ema_trend"] = c.ewm(span=200, adjust=False).mean()
    
    # ATR
    c_prev = c.shift(1)
    tr = np.maximum(h - l, np.maximum(abs(h - c_prev), abs(l - c_prev)))
    df["atr"] = tr.rolling(14).mean()
    
    # Regime
    df["regime"] = 0
    df.loc[c > df["ema_trend"], "regime"] = 1
    df.loc[c < df["ema_trend"], "regime"] = -1
    
    # Crossovers
    fast = df["ema_fast"]
    slow = df["ema_slow"]
    buy_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    sell_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    
    df["signal"] = 0
    df.loc[(df["regime"] == 1) & buy_cross, "signal"] = 1
    df.loc[(df["regime"] == -1) & sell_cross, "signal"] = -1
    
    # Backtest
    trades = []
    in_pos = False
    direction = 0
    entry_p = 0.0
    sl_p = 0.0
    tp_p = 0.0
    pos_size = 0.0
    be_locked = False
    risk_usd = 3.0 # $3 risk per trade
    
    for i in range(200, len(df)):
        d = df.index[i]
        curr_c = c.iloc[i]
        curr_h = h.iloc[i]
        curr_l = l.iloc[i]
        curr_o = o.iloc[i]
        curr_atr = df["atr"].iloc[i]
        sig = df["signal"].iloc[i]
        
        if in_pos:
            pnl = 0.0
            closed = False
            
            if direction == 1:
                # Check BE (+1.0R)
                if not be_locked and curr_h >= (entry_p + (entry_p - sl_p)):
                    sl_p = entry_p * 1.0015
                    be_locked = True
                if curr_l <= sl_p:
                    pnl = (sl_p - entry_p) * pos_size
                    closed = True
                elif curr_h >= tp_p:
                    pnl = (tp_p - entry_p) * pos_size
                    closed = True
            elif direction == -1:
                if not be_locked and curr_l <= (entry_p - (sl_p - entry_p)):
                    sl_p = entry_p * 0.9985
                    be_locked = True
                if curr_h >= sl_p:
                    pnl = (entry_p - sl_p) * pos_size
                    closed = True
                elif curr_l <= tp_p:
                    pnl = (entry_p - tp_p) * pos_size
                    closed = True
                    
            if closed:
                trades.append({
                    "time": d,
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "pnl": pnl,
                    "win": pnl > 0,
                    "be": be_locked
                })
                in_pos = False
                
        if not in_pos and sig != 0:
            direction = sig
            entry_p = curr_o
            sl_dist = 1.0 * curr_atr
            if sl_dist <= 0:
                continue
            pos_size = risk_usd / sl_dist
            if direction == 1:
                sl_p = entry_p - sl_dist
                tp_p = entry_p + (2.2 * sl_dist)
            else:
                sl_p = entry_p + sl_dist
                tp_p = entry_p - (2.2 * sl_dist)
            in_pos = True
            be_locked = False
            
    if not trades:
        print(f"[{symbol} - {interval}] No trades.")
        return
        
    tdf = pd.DataFrame(trades)
    wins = tdf["win"].sum()
    tot = len(tdf)
    net_pnl = tdf["pnl"].sum()
    gross_win = tdf[tdf["pnl"] > 0]["pnl"].sum()
    gross_loss = abs(tdf[tdf["pnl"] < 0]["pnl"].sum())
    pf = gross_win / (gross_loss + 1e-9)
    days = (df.index[-1] - df.index[0]).total_seconds() / 86400
    daily_pnl = net_pnl / max(1, days)
    trades_per_day = tot / max(1, days)
    
    print(f"[{symbol} - {interval}] {days:.1f} Days | Trades: {tot} ({trades_per_day:.1f}/day) | Win Rate: {(wins/tot)*100:.1f}% | Net PnL: ${net_pnl:+.2f} | Daily: ${daily_pnl:+.2f}/day | PF: {pf:.2f}")

if __name__ == "__main__":
    print("Testing across 1m, 3m, 5m, 15m, 1h:")
    for tf in ["1m", "3m", "5m", "15m"]:
        for s in ["SOLUSDT", "BTCUSDT", "ETHUSDT"]:
            test_guardian(s, tf, 3000)
