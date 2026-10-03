"""
VELOCITY SCALPER: Complete 6-Pair Real Sub-Second Tick Audit (September 2026)
Reads directly from /home/rahat/Documents/claude/tick_data
Replays 100+ million authentic Binance sub-second ticks across:
BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, DOGEUSDT, LINKUSDT
"""
import sys
import os
import pandas as pd
from tick_portfolio_engine import run_single_pair_tick_audit, SYMBOLS

def main(month="2026-09"):
    print(f"\n==========================================================================")
    print(f"      COMPREHENSIVE 6-PAIR TICK AUDIT ({month})")
    print(f"      Shared Tick Data Store: /home/rahat/Documents/claude/tick_data")
    print(f"==========================================================================")
    
    results = []
    for s in SYMBOLS:
        res = run_single_pair_tick_audit(symbol=s, month=month, initial_balance=100.0)
        if res:
            results.append(res)
            
    if not results:
        print("No audit results generated.")
        return
        
    df_res = pd.DataFrame(results)
    
    print("\n" + "="*85)
    print(f"               FINAL 6-PAIR REAL-TICK PERFORMANCE SUMMARY ({month})")
    print("="*85)
    print(f"{'SYMBOL':<10} | {'TRADES':<7} | {'WIN RATE':<9} | {'NET PNL':<10} | {'FEES':<8} | {'PF':<6} | {'MAX DD':<8} | {'TARGET DAYS':<11}")
    print("-" * 85)
    
    total_trades = df_res["trades"].sum()
    avg_win_rate = df_res["win_rate"].mean()
    total_pnl = df_res["net_pnl"].sum()
    total_fees = df_res["fees"].sum()
    avg_pf = df_res["pf"].mean()
    max_dd = df_res["max_dd"].max()
    total_targets = df_res["target_days"].sum()
    
    for _, r in df_res.iterrows():
        print(f"{r['symbol']:<10} | {r['trades']:<7} | {r['win_rate']:<8.1f}% | ${r['net_pnl']:<+9.2f} | ${r['fees']:<7.2f} | {r['pf']:<6.2f} | ${r['max_dd']:<7.2f} | {r['target_days']:<11}")
    print("-" * 85)
    print(f"{'PORTFOLIO':<10} | {total_trades:<7} | {avg_win_rate:<8.1f}% | ${total_pnl:<+9.2f} | ${total_fees:<7.2f} | {avg_pf:<6.2f} | ${max_dd:<7.2f} | {total_targets:<11}")
    print("="*85 + "\n")

if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "2026-09"
    main(m)
