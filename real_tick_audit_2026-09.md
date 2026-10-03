# ⚡ Velocity Scalper (5M): Real Sub-Second Tick Audit (2026-09)

> **Platform:** Binance Futures Authentic Sub-Second Tick Archive  
> **Raw Dataset File:** `BTCUSDT-aggTrades-2026-09.zip`  
> **Total Authentic Sub-Second Ticks Processed:** **36,036,629 Ticks**  
> **Testing Engine:** Velocity Scalper (5M Dynamic Momentum Pullback + 200 EMA Regime)  
> **Account Base:** $100.00 | **Risk Model:** 10x Isolated ($25 Margin) | SL: 1.0 ATR | TP: 2.2R | BE Lock: +1.0R  
> **Circuit Breakers Active:** Daily Profit Cap: $3.00 | Daily Loss Limit: $3.00

---

## 1. Executive Performance Summary

| Performance Metric | Real Sub-Second Ticks (2026-09) |
| :--- | :---: |
| **Total Authentic Ticks Evaluated** | **36,036,629 Ticks** |
| **Total Completed Trades** | **45 Trades** (1.5 trades/day) |
| **Winning Trades (Net > 0)** | **23 Wins** |
| **Losing Trades (Net <= 0)** | **22 Losses** |
| **True Win Rate (%)** | **51.11%** |
| **Full Take-Profit (2.2R) Hits** | **6 Trades** |
| **Break-Even (+0.18% Fee Lock) Saves** | **17 Trades** |
| **Stop-Loss Cuts** | **22 Trades** |
| **Gross Profit ($)** | **$-14.33** |
| **Total Exchange Taker Fees Paid** | **$9.00** |
| **Net Profit ($ / %)** | **$-23.35 (-23.4%)** |
| **Profit Factor (PF)** | **0.61** |
| **Average Daily Profit** | **$-0.78 / day** |
| **Average Time in Trade** | **733.4 minutes** |

---

## 2. Daily PnL & Circuit Breaker Tracking

| Date | Day Net PnL | Cumulative Equity | Daily Breaker Status |
| :---: | :---: | :---: | :---: |
| **2026-09-01** | $-2.70 | $97.30 | NORMAL |
| **2026-09-02** | $+5.30 | $102.60 | 🎯 PROFIT LOCKED |
| **2026-09-03** | $-5.40 | $97.20 | 🛡️ LOSS HALT |
| **2026-09-04** | $-5.15 | $92.05 | 🛡️ LOSS HALT |
| **2026-09-05** | $+0.00 | $92.05 | NORMAL |
| **2026-09-06** | $-2.70 | $89.35 | NORMAL |
| **2026-09-07** | $+0.00 | $89.35 | NORMAL |
| **2026-09-08** | $+5.30 | $94.65 | 🎯 PROFIT LOCKED |
| **2026-09-09** | $-1.95 | $92.69 | NORMAL |
| **2026-09-10** | $+5.30 | $97.99 | 🎯 PROFIT LOCKED |
| **2026-09-11** | $-5.40 | $92.59 | 🛡️ LOSS HALT |
| **2026-09-12** | $+0.00 | $92.59 | NORMAL |
| **2026-09-13** | $+0.00 | $92.59 | NORMAL |
| **2026-09-14** | $-5.15 | $87.44 | 🛡️ LOSS HALT |
| **2026-09-15** | $+5.30 | $92.74 | 🎯 PROFIT LOCKED |
| **2026-09-16** | $-1.94 | $90.80 | NORMAL |
| **2026-09-17** | $-2.70 | $88.10 | NORMAL |
| **2026-09-18** | $-5.41 | $82.69 | 🛡️ LOSS HALT |
| **2026-09-19** | $+0.00 | $82.69 | NORMAL |
| **2026-09-20** | $-2.45 | $80.24 | NORMAL |
| **2026-09-21** | $+5.30 | $85.54 | 🎯 PROFIT LOCKED |
| **2026-09-22** | $-2.45 | $83.09 | NORMAL |
| **2026-09-23** | $+5.30 | $88.39 | 🎯 PROFIT LOCKED |
| **2026-09-24** | $-2.20 | $86.19 | NORMAL |
| **2026-09-25** | $+0.25 | $86.44 | NORMAL |
| **2026-09-26** | $+0.25 | $86.70 | NORMAL |
| **2026-09-27** | $-5.40 | $81.29 | 🛡️ LOSS HALT |
| **2026-09-28** | $+0.25 | $81.54 | NORMAL |
| **2026-09-29** | $-2.45 | $79.09 | NORMAL |
| **2026-09-30** | $-2.45 | $76.65 | NORMAL |

---

## 3. Trade-by-Trade Real Sub-Second Tick Log

| # | Entry Time | Dir | Entry ($) | Exit ($) | Net PnL ($) | Duration | Exit Reason |
| :-: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | 2026-09-01 00:20 | LONG | $78772.5 | $77984.77 | $-2.70 | 485.9m | STOP_LOSS |
| 2 | 2026-09-01 08:25 | SHORT | $77984.5 | $76257.15 | +$5.30 | 1585.4m | TAKE_PROFIT |
| 3 | 2026-09-03 00:25 | SHORT | $77082.8 | $77853.63 | $-2.70 | 129.8m | STOP_LOSS |
| 4 | 2026-09-03 02:34 | LONG | $77853.8 | $77080.0 | $-2.70 | 173.3m | STOP_LOSS |
| 5 | 2026-09-04 00:40 | LONG | $81353.0 | $80539.47 | $-2.70 | 356.5m | STOP_LOSS |
| 6 | 2026-09-04 06:36 | LONG | $80539.2 | $80684.17 | +$0.25 | 353.6m | BREAK_EVEN |
| 7 | 2026-09-04 12:30 | LONG | $80684.0 | $79875.0 | $-2.70 | 1.5m | STOP_LOSS |
| 8 | 2026-09-05 01:50 | SHORT | $79558.2 | $80353.78 | $-2.70 | 2748.5m | STOP_LOSS |
| 9 | 2026-09-06 23:38 | SHORT | $80353.9 | $78604.66 | +$5.30 | 1762.0m | TAKE_PROFIT |
| 10 | 2026-09-09 00:10 | LONG | $78585.6 | $78727.05 | +$0.25 | 653.0m | BREAK_EVEN |
| 11 | 2026-09-09 11:03 | LONG | $78726.9 | $78868.61 | +$0.25 | 178.9m | BREAK_EVEN |
| 12 | 2026-09-09 14:01 | LONG | $78868.4 | $78077.55 | $-2.70 | 82.6m | STOP_LOSS |
| 13 | 2026-09-09 15:24 | LONG | $78077.4 | $78217.94 | +$0.25 | 265.8m | BREAK_EVEN |
| 14 | 2026-09-09 19:50 | SHORT | $78217.8 | $76487.59 | +$5.30 | 1644.7m | TAKE_PROFIT |
| 15 | 2026-09-11 01:40 | SHORT | $76745.7 | $77513.16 | $-2.70 | 657.4m | STOP_LOSS |
| 16 | 2026-09-11 12:37 | SHORT | $77513.3 | $78280.92 | $-2.70 | 71.9m | STOP_LOSS |
| 17 | 2026-09-12 02:35 | SHORT | $77228.8 | $77089.79 | +$0.25 | 2843.3m | BREAK_EVEN |
| 18 | 2026-09-14 01:58 | SHORT | $77089.9 | $77861.86 | $-2.70 | 253.3m | STOP_LOSS |
| 19 | 2026-09-14 06:11 | SHORT | $77862.1 | $78634.86 | $-2.70 | 499.9m | STOP_LOSS |
| 20 | 2026-09-15 06:15 | SHORT | $77538.4 | $75832.56 | +$5.30 | 504.1m | TAKE_PROFIT |
| 21 | 2026-09-16 00:00 | SHORT | $75600.0 | $76356.0 | $-2.70 | 1087.2m | STOP_LOSS |
| 22 | 2026-09-16 18:07 | SHORT | $76356.2 | $76218.76 | +$0.25 | 35.7m | BREAK_EVEN |
| 23 | 2026-09-16 18:42 | SHORT | $76219.1 | $76081.91 | +$0.25 | 21.0m | BREAK_EVEN |
| 24 | 2026-09-16 19:03 | SHORT | $76082.1 | $75945.15 | +$0.25 | 40.4m | BREAK_EVEN |
| 25 | 2026-09-16 19:44 | SHORT | $75945.4 | $76702.27 | $-2.70 | 348.0m | STOP_LOSS |
| 26 | 2026-09-17 01:32 | SHORT | $76702.5 | $77460.29 | $-2.70 | 1544.3m | STOP_LOSS |
| 27 | 2026-09-18 03:16 | SHORT | $77460.5 | $78219.7 | $-2.70 | 341.9m | STOP_LOSS |
| 28 | 2026-09-19 00:35 | LONG | $81227.7 | $80415.42 | $-2.70 | 1570.1m | STOP_LOSS |
| 29 | 2026-09-20 02:45 | LONG | $80415.2 | $80559.95 | +$0.25 | 1106.4m | BREAK_EVEN |
| 30 | 2026-09-20 21:11 | LONG | $80559.7 | $82349.11 | +$5.30 | 680.9m | TAKE_PROFIT |
| 31 | 2026-09-22 06:45 | LONG | $85453.0 | $85606.82 | +$0.25 | 405.7m | BREAK_EVEN |
| 32 | 2026-09-22 13:30 | SHORT | $85619.7 | $86472.93 | $-2.70 | 131.8m | STOP_LOSS |
| 33 | 2026-09-22 15:42 | SHORT | $86473.1 | $84596.43 | +$5.30 | 1350.6m | TAKE_PROFIT |
| 34 | 2026-09-24 03:30 | SHORT | $84025.0 | $83873.76 | +$0.25 | 590.1m | BREAK_EVEN |
| 35 | 2026-09-24 13:20 | SHORT | $83873.9 | $84713.55 | $-2.70 | 68.1m | STOP_LOSS |
| 36 | 2026-09-24 14:28 | SHORT | $84713.8 | $84561.32 | +$0.25 | 108.2m | BREAK_EVEN |
| 37 | 2026-09-24 16:16 | SHORT | $84561.5 | $84409.29 | +$0.25 | 971.6m | BREAK_EVEN |
| 38 | 2026-09-25 08:28 | SHORT | $84409.7 | $84257.76 | +$0.25 | 1448.4m | BREAK_EVEN |
| 39 | 2026-09-26 08:36 | SHORT | $84257.9 | $85095.11 | $-2.70 | 1737.7m | STOP_LOSS |
| 40 | 2026-09-27 13:34 | LONG | $85095.3 | $84254.49 | $-2.70 | 520.1m | STOP_LOSS |
| 41 | 2026-09-28 00:55 | SHORT | $84305.6 | $84153.85 | +$0.25 | 933.0m | BREAK_EVEN |
| 42 | 2026-09-28 16:27 | SHORT | $84154.1 | $84002.62 | +$0.25 | 882.4m | BREAK_EVEN |
| 43 | 2026-09-29 07:10 | LONG | $83983.4 | $83148.49 | $-2.70 | 493.0m | STOP_LOSS |
| 44 | 2026-09-29 15:23 | SHORT | $83148.3 | $83981.76 | $-2.70 | 1266.8m | STOP_LOSS |
| 45 | 2026-09-30 12:30 | LONG | $83982.0 | $84133.17 | +$0.25 | 69.5m | BREAK_EVEN |
