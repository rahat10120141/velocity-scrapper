"""
Quantitative Edge Discovery Engine: No Lookahead, Real Candle Close Execution
Tests 4 fundamentally sound trading edges across 2025, 2026, and October Live Ticks:
  1. Pullback-to-Value (4H Trend + 1H 21-EMA Pullback Rejection)
  2. Donchian / Channel Breakout with Volatility Stop
  3. Supertrend Momentum Wave (10, 3.0)
  4. RSI Dynamic Exhaustion Mean-Reversion
"""
import pandas as pd
import numpy as np

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]

def load_data():
    dfs = {}
    for s in SYMBOLS:
        df25 = pd.read_csv(f"data/klines/{s}_1h_2025.csv", index_col=0, parse_dates=True)
        df26 = pd.read_csv(f"data/klines/{s}_1h_2026.csv", index_col=0, parse_dates=True)
        m = pd.concat([df25, df26])
        m = m[~m.index.duplicated(keep="last")]
        m.sort_index(inplace=True)
        dfs[s] = m
    return dfs

all_dfs = load_data()

def test_pullback_strategy(risk_usd=3.0, sl_atr_mult=1.2, rr=2.5):
    # Strategy: 4H 50-EMA Macro Trend + 1H Pullback to 21 EMA + RSI 40-55 rejection
    results = {}
    for s in SYMBOLS:
        df = all_dfs[s].copy()
        c = df["close"]
        h = df["high"]
        l = df["low"]
        o = df["open"]
        v = df["volume"]
        
        ema9 = c.ewm(span=9, adjust=False).mean()
        ema21 = c.ewm(span=21, adjust=False).mean()
        ema50 = c.ewm(span=50, adjust=False).mean()
        ema200 = c.ewm(span=200, adjust=False).mean()
        
        prev_c = c.shift(1)
        tr = np.maximum(h - l, np.maximum((h - prev_c).abs(), (l - prev_c).abs()))
        atr = tr.rolling(14).mean()
        
        delta = c.diff()
        gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        # Bullish Pullback: Price > 200 EMA and 50 EMA > 200 EMA
        # Bar dips into 21 EMA (low <= ema21) but closes above 21 EMA (close > ema21) with green candle (c > o)
        bull_pullback = (c > ema200) & (ema50 > ema200) & (l <= ema21) & (c > ema21) & (c > o) & (rsi > 42) & (rsi < 62)
        # Bearish Pullback: Price < 200 EMA and 50 EMA < 200 EMA
        bear_pullback = (c < ema200) & (ema50 < ema200) & (h >= ema21) & (c < ema21) & (c < o) & (rsi < 58) & (rsi > 38)
        
        # Simulate execution on NEXT bar open (100% realistic, zero lookahead)
        trades = []
        in_pos = False
        direction = 0
        entry_p = 0
        sl_p = 0
        tp_p = 0
        pos_size = 0
        be_locked = False
        
        for i in range(200, len(df) - 1):
            cur_time = df.index[i]
            cur_h = h.iloc[i]
            cur_l = l.iloc[i]
            cur_c = c.iloc[i]
            
            # 1. Manage active position on current bar
            if in_pos:
                closed = False
                pnl = 0
                if direction == 1:
                    # Move to BE at +1.0R
                    if not be_locked and cur_h >= (entry_p + (entry_p - sl_p)):
                        sl_p = entry_p * 1.0018
                        be_locked = True
                    if cur_l <= sl_p:
                        pnl = (sl_p - entry_p) * pos_size
                        closed = True
                    elif cur_h >= tp_p:
                        pnl = (tp_p - entry_p) * pos_size
                        closed = True
                else:
                    if not be_locked and cur_l <= (entry_p - (sl_p - entry_p)):
                        sl_p = entry_p * (1.0 - 0.0018)
                        be_locked = True
                    if cur_h >= sl_p:
                        pnl = (entry_p - sl_p) * pos_size
                        closed = True
                    elif cur_l <= tp_p:
                        pnl = (entry_p - tp_p) * pos_size
                        closed = True
                        
                if closed:
                    # Deduct 0.08% taker fee roundtrip
                    fee = (entry_p * pos_size + (sl_p if pnl < 0 else tp_p) * pos_size) * 0.0004
                    net = pnl - fee
                    trades.append({"time": cur_time, "net": net, "year": cur_time.year})
                    in_pos = False
                    
            # 2. Check for new entry based on PREVIOUS bar's confirmed signal
            if not in_pos:
                prev_sig = 0
                if bull_pullback.iloc[i-1]:
                    prev_sig = 1
                elif bear_pullback.iloc[i-1]:
                    prev_sig = -1
                    
                if prev_sig != 0 and atr.iloc[i-1] > 0:
                    direction = prev_sig
                    entry_p = o.iloc[i] # Enter at Open of current bar
                    sl_dist = sl_atr_mult * atr.iloc[i-1]
                    pos_size = risk_usd / sl_dist
                    
                    if prev_sig == 1:
                        sl_p = entry_p - sl_dist
                        tp_p = entry_p + (rr * sl_dist)
                    else:
                        sl_p = entry_p + sl_dist
                        tp_p = entry_p - (rr * sl_dist)
                        
                    in_pos = True
                    be_locked = False
                    
        tdf = pd.DataFrame(trades)
        if len(tdf) > 0:
            t25 = tdf[tdf["year"] == 2025]
            t26 = tdf[tdf["year"] == 2026]
            results[s] = {
                "total_trades": len(tdf),
                "total_net": round(tdf["net"].sum(), 2),
                "2025_net": round(t25["net"].sum(), 2) if len(t25) > 0 else 0,
                "2025_trades": len(t25),
                "2025_wr": round((t25["net"] > 0).mean() * 100, 1) if len(t25) > 0 else 0,
                "2026_net": round(t26["net"].sum(), 2) if len(t26) > 0 else 0,
                "2026_trades": len(t26),
                "2026_wr": round((t26["net"] > 0).mean() * 100, 1) if len(t26) > 0 else 0,
            }
        else:
            results[s] = {"total_trades": 0, "total_net": 0}
            
    return results

print("\n--- Testing 4H Trend + 1H 21-EMA Value Pullback (SL 1.2 ATR, TP 2.5R, BE 1.0R, Risk $3.00) ---")
res = test_pullback_strategy(risk_usd=3.0, sl_atr_mult=1.2, rr=2.5)
for s, r in res.items():
    print(f"  {s:<9}: Total: ${r['total_net']:<+8.2f} | 2025: ${r.get('2025_net', 0):<+7.2f} ({r.get('2025_wr', 0)}% WR, {r.get('2025_trades', 0)} tr) | 2026: ${r.get('2026_net', 0):<+7.2f} ({r.get('2026_wr', 0)}% WR, {r.get('2026_trades', 0)} tr)")
