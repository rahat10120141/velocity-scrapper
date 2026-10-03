"""
VELOCITY SCALPER: Fast 1m Vectorized Historical Backtester
Simulates exact order execution, slippage, taker fees (0.04% per leg),
and strict trailing stop / breakeven logic on real Binance 1m bars.
"""
import time
import pandas as pd
import numpy as np
from binance_client import BinanceClient
from indicators import compute_all_indicators
from config import STRATEGY_PARAMS, STARTING_CAPITAL, LEVERAGE, MARGIN_PER_TRADE

class VelocityBacktester:
    def __init__(self, symbol="SOLUSDT", bars=10000, params=STRATEGY_PARAMS):
        self.symbol = symbol
        self.bars = bars
        self.params = params
        self.client = BinanceClient(mode="FUTURES")

    def run_backtest(self):
        print(f"Fetching {self.bars} 1-minute bars for {self.symbol}...")
        
        # Backward pagination to collect required bars
        all_bars = []
        end_time = None
        remaining = self.bars
        
        while remaining > 0:
            limit = min(remaining, 1000)
            url_params = {"symbol": self.symbol, "interval": "1m", "limit": limit}
            if end_time:
                url_params["endTime"] = end_time
            data = self.client._request("GET", "/fapi/v1/klines", url_params)
            if not data:
                break
            all_bars = data + all_bars
            remaining -= len(data)
            end_time = data[0][0] - 1
            if len(data) < limit:
                break
            time.sleep(0.04)

        df = pd.DataFrame(all_bars, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_vol", "taker_buy_quote", "ignore"
        ])
        df.drop_duplicates(subset=["open_time"], inplace=True)
        df.sort_values("open_time", inplace=True)
        df["time"] = pd.to_datetime(df["open_time"], unit="ms")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df.set_index("time", inplace=True)

        print(f"Loaded {len(df)} candles from {df.index[0]} to {df.index[-1]}.")
        print("Calculating quantitative indicators...")
        df_ind = compute_all_indicators(df, self.params)

        # Simulation Variables
        balance = STARTING_CAPITAL
        notional_size = MARGIN_PER_TRADE * LEVERAGE  # e.g. $25 * 5 = $125
        fee_rate = 0.0004  # 0.04% taker fee per leg
        
        trades = []
        in_trade = False
        trade_side = None
        entry_price = 0.0
        entry_time = None
        tp_price = 0.0
        sl_price = 0.0
        highest_price = 0.0
        lowest_price = 0.0
        trailing_active = False

        # Loop through candles to simulate real forward-testing
        for i in range(55, len(df_ind)):
            row = df_ind.iloc[i]
            prev = df_ind.iloc[i-1]
            c = row["close"]
            h = row["high"]
            l = row["low"]
            o = row["open"]
            t = row.name

            # 1. Manage Active Trade
            if in_trade:
                duration_bars = (t - entry_time).total_seconds() / 60
                closed = False
                exit_price = c
                exit_reason = ""

                if trade_side == "BUY":
                    if h > highest_price:
                        highest_price = h
                        
                    # Breakeven check (+0.35%)
                    if (highest_price - entry_price) / entry_price >= self.params["breakeven_trigger"]:
                        be_price = entry_price * 1.0010
                        if sl_price < be_price:
                            sl_price = be_price
                            
                    # Trailing Stop check (+0.50%)
                    if (highest_price - entry_price) / entry_price >= self.params["trailing_stop_trigger"]:
                        trailing_active = True
                        new_trail_sl = highest_price * (1 - self.params["trailing_stop_dist"])
                        if new_trail_sl > sl_price:
                            sl_price = new_trail_sl

                    # Check TP
                    if h >= tp_price:
                        exit_price = tp_price
                        exit_reason = "TAKE_PROFIT"
                        closed = True
                    # Check SL
                    elif l <= sl_price:
                        exit_price = sl_price
                        exit_reason = "STOP_LOSS"
                        closed = True
                    # Time Decay Exit
                    elif duration_bars >= self.params["max_trade_duration_minutes"]:
                        exit_price = c
                        exit_reason = "TIME_DECAY"
                        closed = True

                    if closed:
                        pnl_pct = (exit_price - entry_price) / entry_price
                        gross_pnl = notional_size * pnl_pct
                        fees = notional_size * fee_rate * 2
                        net_pnl = gross_pnl - fees
                        balance += net_pnl
                        
                        trades.append({
                            "entry_time": entry_time,
                            "exit_time": t,
                            "side": "BUY",
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "net_pnl": round(net_pnl, 3),
                            "duration_m": duration_bars,
                            "reason": exit_reason,
                            "balance": round(balance, 2)
                        })
                        in_trade = False

                elif trade_side == "SELL":
                    if l < lowest_price:
                        lowest_price = l
                        
                    # Breakeven check
                    if (entry_price - lowest_price) / entry_price >= self.params["breakeven_trigger"]:
                        be_price = entry_price * 0.9990
                        if sl_price > be_price:
                            sl_price = be_price
                            
                    # Trailing Stop check
                    if (entry_price - lowest_price) / entry_price >= self.params["trailing_stop_trigger"]:
                        trailing_active = True
                        new_trail_sl = lowest_price * (1 + self.params["trailing_stop_dist"])
                        if new_trail_sl < sl_price:
                            sl_price = new_trail_sl

                    # Check TP
                    if l <= tp_price:
                        exit_price = tp_price
                        exit_reason = "TAKE_PROFIT"
                        closed = True
                    # Check SL
                    elif h >= sl_price:
                        exit_price = sl_price
                        exit_reason = "STOP_LOSS"
                        closed = True
                    # Time Decay Exit
                    elif duration_bars >= self.params["max_trade_duration_minutes"]:
                        exit_price = c
                        exit_reason = "TIME_DECAY"
                        closed = True

                    if closed:
                        pnl_pct = (entry_price - exit_price) / entry_price
                        gross_pnl = notional_size * pnl_pct
                        fees = notional_size * fee_rate * 2
                        net_pnl = gross_pnl - fees
                        balance += net_pnl
                        
                        trades.append({
                            "entry_time": entry_time,
                            "exit_time": t,
                            "side": "SELL",
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "net_pnl": round(net_pnl, 3),
                            "duration_m": duration_bars,
                            "reason": exit_reason,
                            "balance": round(balance, 2)
                        })
                        in_trade = False

                continue

            # 2. Check for New Entry Signal
            ema_fast = row["ema_fast"]
            ema_slow = row["ema_slow"]
            k_now = row["stoch_k"]
            d_now = row["stoch_d"]
            k_prev = prev["stoch_k"]
            d_prev = prev["stoch_d"]
            bb_lower = row["bb_lower"]
            bb_upper = row["bb_upper"]
            vol_ratio = row["vol_ratio"]
            atr = row["atr"]

            bullish_stoch = (k_now > d_now) and (k_prev <= d_prev) and (k_now <= 45)
            bearish_stoch = (k_now < d_now) and (k_prev >= d_prev) and (k_now >= 55)

            # Dynamic ATR sl/tp
            sl_pct = self.params["sl_pct"]
            tp_pct = self.params["tp_pct"]
            if pd.notna(atr) and atr > 0:
                sl_pct = max(0.0035, min(0.0055, (atr * 1.2) / c))
                tp_pct = max(0.0060, min(0.0095, (atr * 2.0) / c))

            # Long Setup
            if (ema_fast > ema_slow or l <= bb_lower * 1.002) and bullish_stoch and (c > o) and vol_ratio >= 0.9:
                in_trade = True
                trade_side = "BUY"
                entry_price = c
                entry_time = t
                tp_price = entry_price * (1 + tp_pct)
                sl_price = entry_price * (1 - sl_pct)
                highest_price = c
                trailing_active = False

            # Short Setup
            elif (ema_fast < ema_slow or h >= bb_upper * 0.998) and bearish_stoch and (c < o) and vol_ratio >= 0.9:
                in_trade = True
                trade_side = "SELL"
                entry_price = c
                entry_time = t
                tp_price = entry_price * (1 - tp_pct)
                sl_price = entry_price * (1 + sl_pct)
                lowest_price = c
                trailing_active = False

        # Summary Metrics
        if not trades:
            print("No trades generated during this period.")
            return {}

        tdf = pd.DataFrame(trades)
        wins = tdf[tdf["net_pnl"] > 0]
        losses = tdf[tdf["net_pnl"] <= 0]
        
        total_pnl = tdf["net_pnl"].sum()
        win_rate = (len(wins) / len(tdf)) * 100
        profit_factor = abs(wins["net_pnl"].sum() / (losses["net_pnl"].sum() + 1e-9))
        days = (df.index[-1] - df.index[0]).total_seconds() / 86400
        daily_pnl = total_pnl / max(1, days)
        avg_duration = tdf["duration_m"].mean()

        print("\n" + "=" * 55)
        print(f"  BACKTEST RESULTS FOR {self.symbol} (1m CANDLES)")
        print("=" * 55)
        print(f"Total Period:          {days:.1f} days ({len(df)} candles)")
        print(f"Starting Capital:      ${STARTING_CAPITAL:.2f}")
        print(f"Final Balance:         ${balance:.2f} ({((balance - STARTING_CAPITAL)/STARTING_CAPITAL)*100:+.1f}%)")
        print(f"Total Trades:          {len(tdf)} ({len(tdf)/days:.1f} trades/day)")
        print(f"Win Rate:              {win_rate:.1f}% ({len(wins)}W / {len(losses)}L)")
        print(f"Profit Factor:         {profit_factor:.2f}")
        print(f"Net Profit:            ${total_pnl:+.2f}")
        print(f"Average Daily Profit:  ${daily_pnl:+.2f} / day")
        print(f"Average Trade Time:    {avg_duration:.1f} minutes")
        print("=" * 55)

        return {
            "symbol": self.symbol,
            "days": days,
            "trades": len(tdf),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "net_pnl": total_pnl,
            "daily_pnl": daily_pnl,
            "final_balance": balance
        }

if __name__ == "__main__":
    for s in ["SOLUSDT", "BTCUSDT"]:
        bt = VelocityBacktester(symbol=s, bars=3000)
        bt.run_backtest()
