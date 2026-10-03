"""
VELOCITY SCALPER: Ultra-Fast 1H vs 15M Real-Tick Comparison Audit
Streams 36,036,629 authentic sub-second ticks in a SINGLE PASS using C-level csv.reader.
Directly compares:
  - Total trade count & daily frequency
  - Win Rate %
  - Take Profit (2.2R) vs Break-Even (+0.18%) vs Stop-Loss
  - Total Exchange Fees Paid (0.04% each leg)
  - Net Realized Profit ($)
  - Profit Factor & Max Drawdown
"""
import zipfile
import datetime
import time
import io
import csv
import urllib.request
import json
import pandas as pd
import numpy as np

ZIP_PATH_SEP = "/home/rahat/Documents/claude/tick_data/BTCUSDT-aggTrades-2026-09.zip"

def fetch_klines(interval="15m", start_dt=None, end_dt=None):
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    collected = []
    cur_start = start_ts
    headers = {"User-Agent": "Mozilla/5.0"}
    step_ms = 3600 * 1000 if interval == "1h" else 900 * 1000
    
    print(f"Fetching {interval} bars from {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}...")
    while cur_start < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval={interval}&startTime={cur_start}&endTime={end_ts}&limit=1000"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            break
        collected.extend(data)
        cur_start = data[-1][0] + step_ms
        if len(data) < 1000:
            break

    df = pd.DataFrame(collected, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "count", "taker_buy_volume",
        "taker_buy_quote_volume", "ignore"
    ])
    df.drop_duplicates(subset=["open_time"], inplace=True)
    df.sort_values("open_time", inplace=True)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df.set_index("time", inplace=True)
    return df

def generate_signals(interval="15m"):
    warmup_dt = datetime.datetime(2026, 8, 15, 0, 0)
    end_dt = datetime.datetime(2026, 10, 1, 0, 0)
    df = fetch_klines(interval, warmup_dt, end_dt)
    c, h, l = df["close"], df["high"], df["low"]
    
    df["ema_fast"] = c.ewm(span=9, adjust=False).mean()
    df["ema_slow"] = c.ewm(span=21, adjust=False).mean()
    df["ema_trend"] = c.ewm(span=200, adjust=False).mean()
    
    c_prev = c.shift(1)
    tr = np.maximum(h - l, np.maximum(abs(h - c_prev), abs(l - c_prev)))
    df["atr"] = tr.rolling(14).mean()
    
    df["regime"] = 0
    df.loc[c > df["ema_trend"], "regime"] = 1
    df.loc[c < df["ema_trend"], "regime"] = -1
    
    fast, slow = df["ema_fast"], df["ema_slow"]
    buy_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    sell_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    
    df["signal"] = 0
    df.loc[(df["regime"] == 1) & buy_cross, "signal"] = 1
    df.loc[(df["regime"] == -1) & sell_cross, "signal"] = -1

    dur_delta = datetime.timedelta(minutes=15) if interval == "15m" else datetime.timedelta(hours=1)
    signals = []
    
    for i in range(200, len(df)):
        d = df.index[i]
        sig = df["signal"].iloc[i]
        if d.year == 2026 and d.month == 9 and sig != 0:
            atr = df["atr"].iloc[i]
            close_p = df["close"].iloc[i]
            sl_dist = 1.0 * atr
            if sl_dist <= 0: continue
            
            risk_usd = 2.50
            pos_size = risk_usd / sl_dist
            pos_size = min(pos_size, 250.0 / close_p)
            tp_dist = 2.2 * sl_dist

            signals.append({
                "bar_time": d,
                "entry_ts": int((d + dur_delta).timestamp() * 1000),
                "direction": sig,
                "signal_close": close_p,
                "sl_dist": sl_dist,
                "tp_dist": tp_dist,
                "pos_size": pos_size,
                "initial_sl": close_p - sl_dist if sig == 1 else close_p + sl_dist,
                "tp_p": close_p + tp_dist if sig == 1 else close_p - tp_dist,
                "be_trigger": close_p + sl_dist if sig == 1 else close_p - sl_dist,
                "be_sl": close_p * 1.0018 if sig == 1 else close_p * (1.0 - 0.0018)
            })
    return signals

class SimEngine:
    def __init__(self, name, signals):
        self.name = name
        self.signals = signals
        self.next_sig_idx = 0
        self.active_trade = None
        self.trades = []
        self.balance = 100.0
        self.peak_balance = 100.0
        self.max_dd = 0.0
        self.fee_rate = 0.0004
        self.daily_pnl = {}
        
    def on_tick(self, t_ms, price):
        day_bucket = t_ms // 86400000
        if day_bucket not in self.daily_pnl:
            self.daily_pnl[day_bucket] = 0.0
            
        day_pnl = self.daily_pnl[day_bucket]
        breaker_active = (day_pnl >= 3.00) or (day_pnl <= -3.00)

        # Check new entry
        if self.active_trade is None and not breaker_active and self.next_sig_idx < len(self.signals):
            sig = self.signals[self.next_sig_idx]
            if t_ms >= sig["entry_ts"]:
                self.active_trade = dict(sig)
                self.active_trade["entry_price"] = price
                self.active_trade["entry_ts_ms"] = t_ms
                self.active_trade["current_sl"] = price - sig["sl_dist"] if sig["direction"] == 1 else price + sig["sl_dist"]
                self.active_trade["tp_price"] = price + sig["tp_dist"] if sig["direction"] == 1 else price - sig["tp_dist"]
                self.active_trade["be_trigger_price"] = price + sig["sl_dist"] if sig["direction"] == 1 else price - sig["sl_dist"]
                self.active_trade["be_sl_price"] = price * 1.0018 if sig["direction"] == 1 else price * 0.9982
                self.active_trade["be_locked"] = False
                self.next_sig_idx += 1

        # Check active trade
        if self.active_trade is not None:
            d = self.active_trade["direction"]
            entry_p = self.active_trade["entry_price"]
            pos_size = self.active_trade["pos_size"]
            closed = False
            exit_p = price
            reason = ""

            if d == 1:
                if not self.active_trade["be_locked"] and price >= self.active_trade["be_trigger_price"]:
                    self.active_trade["current_sl"] = self.active_trade["be_sl_price"]
                    self.active_trade["be_locked"] = True
                if price >= self.active_trade["tp_price"]:
                    exit_p = self.active_trade["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif price <= self.active_trade["current_sl"]:
                    exit_p = self.active_trade["current_sl"]
                    reason = "BREAK_EVEN" if self.active_trade["be_locked"] else "STOP_LOSS"
                    closed = True
            elif d == -1:
                if not self.active_trade["be_locked"] and price <= self.active_trade["be_trigger_price"]:
                    self.active_trade["current_sl"] = self.active_trade["be_sl_price"]
                    self.active_trade["be_locked"] = True
                if price <= self.active_trade["tp_price"]:
                    exit_p = self.active_trade["tp_price"]
                    reason = "TAKE_PROFIT"
                    closed = True
                elif price >= self.active_trade["current_sl"]:
                    exit_p = self.active_trade["current_sl"]
                    reason = "BREAK_EVEN" if self.active_trade["be_locked"] else "STOP_LOSS"
                    closed = True

            if closed:
                gross = (exit_p - entry_p) * pos_size if d == 1 else (entry_p - exit_p) * pos_size
                fees = (entry_p * pos_size + exit_p * pos_size) * self.fee_rate
                net = gross - fees
                dur_m = round((t_ms - self.active_trade["entry_ts_ms"]) / 60000, 1)
                
                self.balance += net
                self.daily_pnl[day_bucket] += net
                if self.balance > self.peak_balance:
                    self.peak_balance = self.balance
                dd = self.peak_balance - self.balance
                if dd > self.max_dd:
                    self.max_dd = dd

                self.trades.append({
                    "entry_ts": self.active_trade["entry_ts_ms"],
                    "exit_ts": t_ms,
                    "direction": "LONG" if d == 1 else "SHORT",
                    "net_pnl": round(net, 2),
                    "gross_pnl": round(gross, 2),
                    "fees": round(fees, 2),
                    "reason": reason,
                    "duration_m": dur_m
                })
                self.active_trade = None

    def get_summary(self):
        tot = len(self.trades)
        wins = [t for t in self.trades if t["net_pnl"] > 0]
        losses = [t for t in self.trades if t["net_pnl"] <= 0]
        wr = (len(wins) / tot * 100) if tot > 0 else 0
        net = sum(t["net_pnl"] for t in self.trades)
        gross_w = sum(t["net_pnl"] for t in wins)
        gross_l = abs(sum(t["net_pnl"] for t in losses))
        pf = gross_w / (gross_l + 1e-9)
        tot_fees = sum(t["fees"] for t in self.trades)
        
        target_days = sum(1 for p in self.daily_pnl.values() if p >= 3.00)
        loss_days = sum(1 for p in self.daily_pnl.values() if p <= -3.00)
        
        return {
            "name": self.name,
            "total_trades": tot,
            "trades_per_day": round(tot / 30, 2),
            "win_rate": round(wr, 1),
            "wins": len(wins),
            "losses": len(losses),
            "tp_hits": sum(1 for t in self.trades if t["reason"] == "TAKE_PROFIT"),
            "be_saves": sum(1 for t in self.trades if t["reason"] == "BREAK_EVEN"),
            "sl_cuts": sum(1 for t in self.trades if t["reason"] == "STOP_LOSS"),
            "net_pnl": round(net, 2),
            "fees": round(tot_fees, 2),
            "pf": round(pf, 2),
            "max_dd": round(self.max_dd, 2),
            "target_days": target_days,
            "loss_days": loss_days
        }

if __name__ == "__main__":
    print("=" * 80)
    print("  SIMULTANEOUS 1H vs 15M TICK REPLAY (SINGLE-PASS C-OPTIMIZED)")
    print("=" * 80)
    
    sigs_1h = generate_signals("1h")
    sigs_15m = generate_signals("15m")
    print(f"1H Signals: {len(sigs_1h)} | 15M Signals: {len(sigs_15m)}")
    
    eng_1h = SimEngine("1H Timeframe", sigs_1h)
    eng_15m = SimEngine("15M Timeframe", sigs_15m)
    
    t0 = time.time()
    print("Streaming 36,036,629 ticks from BTCUSDT-aggTrades-2026-09.zip...")
    
    with zipfile.ZipFile(ZIP_PATH_SEP, "r") as z:
        csv_name = z.namelist()[0]
        with z.open(csv_name, "r") as f:
            reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
            next(reader, None) # skip header
            
            for row in reader:
                t_ms = int(row[5])
                price = float(row[1])
                eng_1h.on_tick(t_ms, price)
                eng_15m.on_tick(t_ms, price)
                
    elapsed = time.time() - t0
    print(f"Finished replaying 36M ticks in {elapsed:.1f}s!\n")
    
    s_1h = eng_1h.get_summary()
    s_15m = eng_15m.get_summary()
    
    print("=" * 80)
    print(f"{'Metric':<28} | {'1H TIMEFRAME':<20} | {'15M TIMEFRAME':<20}")
    print("-" * 80)
    print(f"{'Total Trades Completed':<28} | {s_1h['total_trades']:<20} | {s_15m['total_trades']:<20}")
    print(f"{'Trades Per Day':<28} | {s_1h['trades_per_day']:<20} | {s_15m['trades_per_day']:<20}")
    print(f"{'Win Rate (%)':<28} | {s_1h['win_rate']:<19}% | {s_15m['win_rate']:<19}%")
    print(f"{'Take Profit (2.2R) Hits':<28} | {s_1h['tp_hits']:<20} | {s_15m['tp_hits']:<20}")
    print(f"{'Break-Even (+0.18%) Saves':<28} | {s_1h['be_saves']:<20} | {s_15m['be_saves']:<20}")
    print(f"{'Stop-Loss Cuts':<28} | {s_1h['sl_cuts']:<20} | {s_15m['sl_cuts']:<20}")
    print(f"{'Total Fees Paid':<28} | ${s_1h['fees']:<19} | ${s_15m['fees']:<19}")
    print(f"{'Net Realized Profit':<28} | ${s_1h['net_pnl']:<+19.2f} | ${s_15m['net_pnl']:<+19.2f}")
    print(f"{'Profit Factor':<28} | {s_1h['pf']:<20} | {s_15m['pf']:<20}")
    print(f"{'Max Drawdown':<28} | ${s_1h['max_dd']:<19.2f} | ${s_15m['max_dd']:<19.2f}")
    print(f"{'Target Hit Days ($3 Lock)':<28} | {s_1h['target_days']:<20} | {s_15m['target_days']:<20}")
    print(f"{'Loss Halt Days (-$3 Defense)':<28} | {s_1h['loss_days']:<20} | {s_15m['loss_days']:<20}")
    print("=" * 80)
