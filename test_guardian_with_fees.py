import pandas as pd
import numpy as np
from binance_client import BinanceClient

client = BinanceClient(mode="FUTURES")

def test_guardian_with_fees(symbol="BTCUSDT", interval="3m", total_bars=3000):
    df = client.fetch_klines(symbol, interval=interval, limit=total_bars)
    c, h, l, o = df["close"], df["high"], df["low"], df["open"]
    
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
    
    trades = []
    in_pos = False
    direction = 0
    entry_p = 0.0
    sl_p = 0.0
    tp_p = 0.0
    pos_size = 0.0
    be_locked = False
    risk_usd = 2.50 # $2.50 risk per trade
    fee_rate = 0.0004 # 0.04% per trade (0.08% roundtrip)
    
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
            exit_p = curr_c
            
            if direction == 1:
                if not be_locked and curr_h >= (entry_p + (entry_p - sl_p)):
                    sl_p = entry_p * 1.0018 # BE + fee cover
                    be_locked = True
                if curr_l <= sl_p:
                    exit_p = sl_p
                    closed = True
                elif curr_h >= tp_p:
                    exit_p = tp_p
                    closed = True
                if closed:
                    pnl = (exit_p - entry_p) * pos_size
            elif direction == -1:
                if not be_locked and curr_l <= (entry_p - (sl_p - entry_p)):
                    sl_p = entry_p * 0.9982
                    be_locked = True
                if curr_h >= sl_p:
                    exit_p = sl_p
                    closed = True
                elif curr_l <= tp_p:
                    exit_p = tp_p
                    closed = True
                if closed:
                    pnl = (entry_p - exit_p) * pos_size
                    
            if closed:
                notional_val = entry_p * pos_size
                fees = notional_val * fee_rate * 2
                net_pnl = pnl - fees
                trades.append({
                    "time": d,
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "gross_pnl": pnl,
                    "fees": fees,
                    "net_pnl": net_pnl,
                    "win": net_pnl > 0,
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
            
            # Ensure notional size doesn't exceed $125 (5x on $25)
            notional = entry_p * pos_size
            if notional > 150.0:
                pos_size = 150.0 / entry_p
                sl_dist = risk_usd / pos_size
                
            if direction == 1:
                sl_p = entry_p - sl_dist
                tp_p = entry_p + (2.2 * sl_dist)
            else:
                sl_p = entry_p + sl_dist
                tp_p = entry_p - (2.2 * sl_dist)
            in_pos = True
            be_locked = False
            
    tdf = pd.DataFrame(trades)
    tot = len(tdf)
    if tot == 0:
        return
    wins = tdf["win"].sum()
    net_pnl = tdf["net_pnl"].sum()
    gross_win = tdf[tdf["net_pnl"] > 0]["net_pnl"].sum()
    gross_loss = abs(tdf[tdf["net_pnl"] < 0]["net_pnl"].sum())
    pf = gross_win / (gross_loss + 1e-9)
    days = (df.index[-1] - df.index[0]).total_seconds() / 86400
    daily_pnl = net_pnl / max(1, days)
    
    print(f"[{symbol} - {interval} WITH FULL FEES] {days:.1f} Days:")
    print(f"  Trades: {tot} ({tot/days:.1f}/day) | Win Rate: {(wins/tot)*100:.1f}%")
    print(f"  Gross PnL: ${tdf['gross_pnl'].sum():+.2f} | Total Fees: ${tdf['fees'].sum():.2f} | Net PnL: ${net_pnl:+.2f}")
    print(f"  Daily Net Profit: ${daily_pnl:+.2f} / day | Profit Factor: {pf:.2f}")
    print("-" * 65)

if __name__ == "__main__":
    print("TESTING FULL FEE IMPACT (0.08% roundtrip):")
    for s in ["SOLUSDT", "BTCUSDT", "ETHUSDT"]:
        test_guardian_with_fees(s, "3m", 3000)
    for s in ["SOLUSDT", "BTCUSDT", "ETHUSDT"]:
        test_guardian_with_fees(s, "5m", 3000)
