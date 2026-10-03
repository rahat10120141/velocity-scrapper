from engine import VelocityEngine

eng = VelocityEngine()
print("Starting single test scan cycle...")
eng.scan_cycle()
status = eng.get_status()
print(f"Current Balance: ${status['current_balance']}")
print(f"Today PnL: ${status['today_realized_pnl']} (Target: ${status['daily_target']})")
print(f"Circuit Breaker Status: {status['circuit_breaker']}")
print("Market Radar (5m):")
for k, v in status["market_radar"].items():
    print(f"  {k:8s} | Price: ${v['price']} | Regime: {v['regime']:15s} | Signal: {v['signal_label']:5s} | Fast/Slow: {v['ema_fast']}/{v['ema_slow']} | 200 EMA: {v['ema_trend']}")
