import sys
import os
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtester import run_backtest_on_binance

print("Testing Guardian on 5m and 15m timeframes across SOL, BTC, ETH...")

for interval in ["5m", "15m"]:
    print(f"\n################# TIMEFRAME: {interval} #################")
    for sym in ["SOLUSDT", "BTCUSDT", "ETHUSDT"]:
        res = run_backtest_on_binance(symbol=sym, interval=interval, total_bars=3000, initial_balance=100.0, risk_pct=0.03)
        if res:
            days = (pd.to_datetime(res["end_date"]) - pd.to_datetime(res["start_date"])).total_seconds() / 86400
            daily_profit = res["net_pnl"] / max(1, days)
            trades_per_day = res["trades"] / max(1, days)
            print(f"[{res['symbol']} - {res['timeframe']}] {days:.1f} days:")
            print(f"  Trades: {res['trades']} ({trades_per_day:.1f}/day) | Win Rate: {res['win_rate']:.1f}%")
            print(f"  Net Profit: ${res['net_pnl']:+.2f} | Daily: ${daily_profit:+.2f}/day | PF: {res['profit_factor']:.2f} | MaxDD: ${res['max_drawdown']:.2f}")
