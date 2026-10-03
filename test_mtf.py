import pandas as pd
import numpy as np
from binance_client import BinanceClient

client = BinanceClient(mode="FUTURES")

def test_mtf(symbol="BTCUSDT"):
    print(f"\n=================== MTF BACKTEST: {symbol} ===================")
    # Fetch 3m bars (e.g. 3000 bars ~ 6.2 days)
    df_3m = client.fetch_klines(symbol, interval="3m", limit=3000)
    # Fetch 15m bars
    df_15m = client.fetch_klines(symbol, interval="15m", limit=1000)
    
    # 15m EMA Trend
    df_15m["ema_trend_15m"] = df_15m["close"].ewm(span=34, adjust=False).mean()
    df_15m["trend_dir"] = np.where(df_15m["close"] > df_15m["ema_trend_15m"], 1, -1)
    
    # Reindex/merge 15m trend onto 3m bars
    df_3m["trend_dir"] = df_15m["trend_dir"].reindex(df_3m.index, method="ffill")
    
    # 3m indicators
    c = df_3m["close"]
    df_3m["ema_9"] = c.ewm(span=9, adjust=False).mean()
    df_3m["ema_21"] = c.ewm(span=21, adjust=False).mean()
    
    # StochRSI
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    min_rsi = rsi.rolling(14).min()
    max_rsi = rsi.rolling(14).max()
    stoch = ((rsi - min_rsi) / (max_rsi - min_rsi + 1e-9)) * 100
    df_3m["stoch_k"] = stoch.rolling(3).mean()
    df_3m["stoch_d"] = df_3m["stoch_k"].rolling(3).mean()
    
    # Volume
    df_3m["vol_ma"] = df_3m["volume"].rolling(20).mean()
    df_3m["vol_ratio"] = df_3m["volume"] / (df_3m["vol_ma"] + 1e-9)
    
    notional = 125.0
    fee_rate = 0.0004 * 2
    
    for tp_pct in [0.007, 0.009, 0.012]:
        for sl_pct in [0.004, 0.005]:
            trades = []
            in_trade = False
            ep = 0.0
            tp = 0.0
            sl = 0.0
            peak = 0.0
            be_active = False
            dur = 0
            
            for i in range(50, len(df_3m)):
                row = df_3m.iloc[i]
                prev = df_3m.iloc[i-1]
                close_p = row["close"]
                high_p = row["high"]
                low_p = row["low"]
                open_p = row["open"]
                
                if in_trade:
                    dur += 1
                    if side == "BUY":
                        if high_p > peak:
                            peak = high_p
                        # Breakeven trigger at +0.35%
                        if not be_active and (peak - ep) / ep >= 0.0035:
                            sl = ep * 1.0008 # BE + fee
                            be_active = True
                            
                        if high_p >= tp:
                            net = (tp - ep) / ep * notional - (notional * fee_rate)
                            trades.append(("TP", net, dur))
                            in_trade = False
                        elif low_p <= sl:
                            net = (sl - ep) / ep * notional - (notional * fee_rate)
                            trades.append(("SL" if not be_active else "BE", net, dur))
                            in_trade = False
                        elif dur >= 15:
                            net = (close_p - ep) / ep * notional - (notional * fee_rate)
                            trades.append(("TIME", net, dur))
                            in_trade = False
                            
                    elif side == "SELL":
                        if low_p < peak:
                            peak = low_p
                        # Breakeven trigger at +0.35%
                        if not be_active and (ep - peak) / ep >= 0.0035:
                            sl = ep * 0.9992
                            be_active = True
                            
                        if low_p <= tp:
                            net = (ep - tp) / ep * notional - (notional * fee_rate)
                            trades.append(("TP", net, dur))
                            in_trade = False
                        elif high_p >= sl:
                            net = (ep - sl) / ep * notional - (notional * fee_rate)
                            trades.append(("SL" if not be_active else "BE", net, dur))
                            in_trade = False
                        elif dur >= 15:
                            net = (ep - close_p) / ep * notional - (notional * fee_rate)
                            trades.append(("TIME", net, dur))
                            in_trade = False
                    continue
                
                # Signal:
                trend_15m = row["trend_dir"]
                stoch_cross_up = (row["stoch_k"] > row["stoch_d"]) and (prev["stoch_k"] <= prev["stoch_d"]) and (row["stoch_k"] <= 35)
                stoch_cross_down = (row["stoch_k"] < row["stoch_d"]) and (prev["stoch_k"] >= prev["stoch_d"]) and (row["stoch_k"] >= 65)
                
                if trend_15m == 1 and stoch_cross_up and (close_p > open_p) and (row["vol_ratio"] >= 0.9):
                    in_trade = True
                    side = "BUY"
                    ep = close_p
                    tp = ep * (1 + tp_pct)
                    sl = ep * (1 - sl_pct)
                    peak = ep
                    be_active = False
                    dur = 0
                elif trend_15m == -1 and stoch_cross_down and (close_p < open_p) and (row["vol_ratio"] >= 0.9):
                    in_trade = True
                    side = "SELL"
                    ep = close_p
                    tp = ep * (1 - tp_pct)
                    sl = ep * (1 + sl_pct)
                    peak = ep
                    be_active = False
                    dur = 0
            
            if trades:
                tdf = pd.DataFrame(trades, columns=["reason", "net", "dur"])
                wins = tdf[tdf["net"] > 0]
                losses = tdf[tdf["net"] <= 0]
                total_pnl = tdf["net"].sum()
                wr = len(wins) / len(tdf) * 100
                days = (df_3m.index[-1] - df_3m.index[0]).total_seconds() / 86400
                daily = total_pnl / max(1, days)
                pf = wins["net"].sum() / (abs(losses["net"].sum()) + 1e-9)
                print(f"TP {tp_pct*100:.1f}% | SL {sl_pct*100:.1f}% -> Trades: {len(tdf):2d} | WinRate: {wr:.1f}% | ProfitFactor: {pf:.2f} | Net$: {total_pnl:+.2f} | Daily$: {daily:+.2f}/day | AvgDur: {tdf['dur'].mean()*3:.1f}m")

if __name__ == "__main__":
    test_mtf("BTCUSDT")
    test_mtf("SOLUSDT")
    test_mtf("ETHUSDT")
