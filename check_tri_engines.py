import json

for engine in ["ladder", "trailing", "runner"]:
    fpath = f"bot_state_{engine}.json"
    try:
        with open(fpath) as f:
            d = json.load(f)
        trades = d.get("closed_trades", [])
        wins = [t for t in trades if t.get("net_pnl", 0) > 0]
        losses = [t for t in trades if t.get("net_pnl", 0) <= 0]
        net_pnl = sum(t.get("net_pnl", 0) for t in trades)
        curr_bal = d.get("current_balance", 0)
        reasons = {}
        for t in trades:
            r = t.get("reason", "UNKNOWN")
            reasons[r] = reasons.get(r, 0) + 1
        start_bal = d.get("starting_balance", 100)
        cb = d.get("circuit_breaker")
        act = len(d.get("active_positions", []))
        wr = len(wins)/max(1, len(trades))*100
        print(f"\n=================== ENGINE: {engine.upper()} ===================")
        print(f"Starting: ${start_bal:.2f} | Current: ${curr_bal:.2f} | Net: ${net_pnl:+.2f}")
        print(f"Trades: {len(trades)} | Wins: {len(wins)} | Losses: {len(losses)} | Win Rate: {wr:.1f}%")
        print(f"Circuit Breaker: {cb} | Active Positions: {act}")
        print(f"Exit Reasons: {reasons}")
        
        print("Recent 5 trades:")
        for t in trades[-5:]:
            tm = t.get('time')
            sym = t.get('symbol')
            dr = t.get('direction')
            pnl = t.get('net_pnl', 0)
            rs = t.get('reason')
            print(f"  {tm} | {sym} {dr} | Net: ${pnl:+.2f} | {rs}")
    except Exception as e:
        print(f"Error {engine}: {e}")
