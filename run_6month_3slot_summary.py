"""
VELOCITY SCALPER: Parallel 6-Month Real-Tick Audit (Max 3 Slots)
Processes April 2026 to September 2026 in parallel across CPU cores.
Calculates exact monthly average profit on $100 starting balance.
"""
import os
import time
import datetime
from concurrent.futures import ProcessPoolExecutor
from audit_2026_multi_month_concurrency import evaluate_month_candidates, simulate_portfolio

MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]

def process_month(m):
    t0 = time.time()
    cands = evaluate_month_candidates(m)
    res = simulate_portfolio(cands, max_concurrent=3)
    res["month"] = m
    res["candidate_count"] = len(cands)
    res["elapsed"] = round(time.time() - t0, 1)
    return res

if __name__ == "__main__":
    print("=" * 85)
    print("  VELOCITY SCALPER: PARALLEL 6-MONTH TICK AUDIT (MAX 3 SLOTS)")
    print("  Replaying 600+ Million Authentic Binance Sub-Second Ticks across 6 Pairs")
    print("=" * 85)
    
    t_start = time.time()
    with ProcessPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(process_month, MONTHS))
        
    print("\n" + "=" * 85)
    print(f"{'MONTH':<10} | {'TRADES':<7} | {'WIN RATE':<9} | {'NET PNL':<11} | {'FEES':<8} | {'PF':<6} | {'MAX DD':<8} | {'TARGET DAYS':<11}")
    print("-" * 85)
    
    tot_trades = 0
    tot_pnl = 0.0
    tot_fees = 0.0
    all_dds = []
    tot_targets = 0
    tot_loss_days = 0
    
    for r in results:
        tot_trades += r["trades"]
        tot_pnl += r["net_pnl"]
        tot_fees += r["fees"]
        all_dds.append(r["max_dd"])
        tot_targets += r["target_days"]
        tot_loss_days += r["loss_days"]
        print(f"{r['month']:<10} | {r['trades']:<7} | {r['win_rate']:<8.1f}% | ${r['net_pnl']:<+10.2f} | ${r['fees']:<7.2f} | {r['pf']:<6.2f} | ${r['max_dd']:<7.2f} | {r['target_days']:<11}")
        
    avg_monthly_pnl = tot_pnl / len(results)
    avg_trades_month = tot_trades / len(results)
    avg_win_rate = sum(r["win_rate"] for r in results) / len(results)
    max_portfolio_dd = max(all_dds)
    
    print("-" * 85)
    print(f"{'TOTAL 6M':<10} | {tot_trades:<7} | {avg_win_rate:<8.1f}% | ${tot_pnl:<+10.2f} | ${tot_fees:<7.2f} |        | ${max_portfolio_dd:<7.2f} | {tot_targets:<11}")
    print("=" * 85)
    print(f"\n📊 SUMMARY STATS (6-Month Historical Real-Tick Average):")
    print(f"  • Average Monthly Net Profit:   ${avg_monthly_pnl:+.2f} / month ({avg_monthly_pnl:.1f}% on $100 capital)")
    print(f"  • Average Trades Per Month:     {avg_trades_month:.1f} trades / month ({avg_trades_month/30:.1f} trades/day)")
    print(f"  • Average Win Rate:             {avg_win_rate:.1f}%")
    print(f"  • Total Net Profit (6 Months):  ${tot_pnl:+.2f}")
    print(f"  • Total Return on $100 Base:    +{tot_pnl:.1f}% (Account grows from $100 to ${100+tot_pnl:.2f})")
    print(f"  • Maximum Monthly Drawdown:     ${max_portfolio_dd:.2f}")
    print(f"  • Total Target Hit Days:        {tot_targets} days ($3 profit lock triggered)")
    print(f"  • Total Loss Defense Days:      {tot_loss_days} days (-$3 circuit breaker halt)")
    print(f"  • Execution Time:               {time.time() - t_start:.1f}s")
