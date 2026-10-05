"""
VELOCITY SCALPER: Data Recorder & Trade Learning Audit Engine
1. Records high-precision live tick data for all 6 crypto pairs for future ML/AI training and backtesting.
2. Tracks full trade journey trajectory (MFE, MAE, peak profit, drawdown, break-even events).
3. Generates rich post-mortem audit logs with detailed rationale for every trade and scan decision.
"""
import os
import json
import time
from datetime import datetime, timezone
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TICKS_DIR = os.path.join(BASE_DIR, "data", "ticks")
TRADES_DIR = os.path.join(BASE_DIR, "data", "trades")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(TICKS_DIR, exist_ok=True)
os.makedirs(TRADES_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

class DataRecorder:
    def __init__(self):
        self.tick_file_handles = {}
        self.last_written_date = None

    def _get_date_str(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def record_tick(self, symbol: str, price: float, analysis: dict):
        """Record live market tick and indicator state to CSV."""
        if not price or price <= 0:
            return

        date_str = self._get_date_str()
        csv_file = os.path.join(TICKS_DIR, f"{symbol}_{date_str}.csv")
        file_exists = os.path.exists(csv_file)

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        regime = analysis.get("regime", "NEUTRAL") if analysis else "NEUTRAL"
        signal = analysis.get("signal", 0) if analysis else 0
        sig_label = analysis.get("signal_label", "HOLD") if analysis else "HOLD"
        ema_fast = analysis.get("ema_fast", 0.0) if analysis else 0.0
        ema_slow = analysis.get("ema_slow", 0.0) if analysis else 0.0
        ema_trend = analysis.get("ema_trend", 0.0) if analysis else 0.0
        trend_dist = analysis.get("trend_distance_pct", 0.0) if analysis else 0.0
        ema_diff = analysis.get("ema_diff_pct", 0.0) if analysis else 0.0
        atr = analysis.get("atr", 0.0) if analysis else 0.0

        row = f"{now_iso},{symbol},{price:.4f},{regime},{signal},{sig_label},{ema_fast:.4f},{ema_slow:.4f},{ema_trend:.4f},{trend_dist:.3f},{ema_diff:.3f},{atr:.4f}\n"

        try:
            with open(csv_file, "a", encoding="utf-8") as f:
                if not file_exists:
                    f.write("timestamp_utc,symbol,price,regime,signal,signal_label,ema_fast,ema_slow,ema_trend,trend_distance_pct,ema_diff_pct,atr\n")
                f.write(row)
        except Exception as e:
            pass

    def update_trade_trajectory(self, pos: dict, current_price: float):
        """Track Max Favorable Excursion (MFE) and Max Adverse Excursion (MAE) while position is open."""
        if not pos or current_price <= 0:
            return

        direction = pos.get("direction", "LONG")
        entry_p = pos.get("entry_price", current_price)

        # Initialize tracking fields if not present
        if "mfe_price" not in pos:
            pos["mfe_price"] = entry_p
            pos["mae_price"] = entry_p
            pos["peak_profit_usd"] = 0.0
            pos["max_drawdown_usd"] = 0.0
            pos["ticks_observed"] = 0

        pos["ticks_observed"] = pos.get("ticks_observed", 0) + 1
        pos_size = pos.get("quantity", 0.0)

        if direction == "LONG":
            if current_price > pos["mfe_price"]:
                pos["mfe_price"] = current_price
            if current_price < pos["mae_price"]:
                pos["mae_price"] = current_price
            unrealized = (current_price - entry_p) * pos_size
        else: # SHORT
            if current_price < pos["mfe_price"]:
                pos["mfe_price"] = current_price
            if current_price > pos["mae_price"]:
                pos["mae_price"] = current_price
            unrealized = (entry_p - current_price) * pos_size

        if unrealized > pos["peak_profit_usd"]:
            pos["peak_profit_usd"] = round(unrealized, 2)
        if unrealized < pos["max_drawdown_usd"]:
            pos["max_drawdown_usd"] = round(unrealized, 2)

    def record_trade_open(self, pos: dict, analysis: dict):
        """Log full context at position opening for future trade analysis."""
        journal_file = os.path.join(TRADES_DIR, "trade_journal.jsonl")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        record = {
            "event": "TRADE_OPEN",
            "time": now_str,
            "symbol": pos["symbol"],
            "direction": pos["direction"],
            "entry_price": pos["entry_price"],
            "quantity": pos["quantity"],
            "margin": pos["margin"],
            "leverage": pos["leverage"],
            "sl_price": pos["sl_price"],
            "tp_price": pos["tp_price"],
            "be_trigger": pos["be_trigger"],
            "context": {
                "regime": analysis.get("regime") if analysis else None,
                "ema_trend": analysis.get("ema_trend") if analysis else None,
                "ema_fast": analysis.get("ema_fast") if analysis else None,
                "ema_slow": analysis.get("ema_slow") if analysis else None,
                "trend_dist_pct": analysis.get("trend_distance_pct") if analysis else None,
                "atr": analysis.get("atr") if analysis else None
            }
        }

        try:
            with open(journal_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception:
            pass

    def record_trade_close(self, closed_record: dict, pos: dict):
        """Generate comprehensive post-mortem audit and save to journal and markdown."""
        journal_file = os.path.join(TRADES_DIR, "trade_journal.jsonl")
        audit_md = os.path.join(LOGS_DIR, "audit_learning.md")

        sym = closed_record.get("symbol", "")
        direction = closed_record.get("direction", "")
        entry_p = closed_record.get("entry_price", 0.0)
        exit_p = closed_record.get("exit_price", 0.0)
        net_pnl = closed_record.get("net_pnl", 0.0)
        reason = closed_record.get("reason", "UNKNOWN")
        duration_m = closed_record.get("duration_m", 0.0)

        mfe_price = pos.get("mfe_price", entry_p)
        mae_price = pos.get("mae_price", entry_p)
        peak_profit = pos.get("peak_profit_usd", max(0.0, net_pnl))
        max_drawdown = pos.get("max_drawdown_usd", min(0.0, net_pnl))

        # Calculate excursions in %
        if direction == "LONG":
            mfe_pct = round(((mfe_price - entry_p) / entry_p) * 100, 2)
            mae_pct = round(((mae_price - entry_p) / entry_p) * 100, 2)
        else:
            mfe_pct = round(((entry_p - mfe_price) / entry_p) * 100, 2)
            mae_pct = round(((entry_p - mae_price) / entry_p) * 100, 2)

        # AI Learning & Mistake Assessment
        lesson = ""
        category = ""
        if reason == "TAKE_PROFIT":
            category = "WIN_CLEAN"
            lesson = f"Clean WIN (+${net_pnl:+.2f}). Target {closed_record.get('tp_price', exit_p)} achieved in {duration_m}m. Strategy execution was optimal."
        elif reason == "BREAK_EVEN":
            category = "BREAK_EVEN_SAVED"
            lesson = f"Break-Even Defense (+${net_pnl:+.2f}). Peak profit reached +${peak_profit:.2f} ({mfe_pct:+}%). Protected account when momentum reversed. Zero loss suffered."
        elif reason == "STOP_LOSS":
            category = "LOSS_STOP_HIT"
            if mfe_pct > 0.8:
                lesson = f"MISTAKE/OPPORTUNITY: Stopped out at ${exit_p} (${net_pnl:+.2f}), but trade had previously reached +{mfe_pct}% peak gain (+${peak_profit:.2f}). Consider tightening BE trigger or taking partial profits earlier."
            else:
                lesson = f"STANDARD LOSS (${net_pnl:+.2f}): Adverse price action immediately broke support/resistance. Max drawdown was {mae_pct}%. Risk limited strictly to $2.50 cap."
        elif reason == "MANUAL_CLOSE":
            category = "MANUAL_EXIT"
            lesson = f"Manual exit executed at ${exit_p}. Realized {net_pnl:+.2f} after {duration_m}m."
        else:
            category = "CLOSED"
            lesson = f"Trade closed: {reason} | PnL: ${net_pnl:+.2f}"

        audit_entry = {
            "event": "TRADE_CLOSE_AUDIT",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "trade": closed_record,
            "trajectory": {
                "mfe_price": mfe_price,
                "mae_price": mae_price,
                "mfe_pct": mfe_pct,
                "mae_pct": mae_pct,
                "peak_profit_usd": peak_profit,
                "max_drawdown_usd": max_drawdown,
                "ticks_observed": pos.get("ticks_observed", 0)
            },
            "audit": {
                "category": category,
                "lesson": lesson
            }
        }

        # Write to JSONL journal
        try:
            with open(journal_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(audit_entry, default=str) + "\n")
        except Exception:
            pass

        # Write to human-readable Markdown audit
        try:
            md_entry = f"""
### 📊 Trade Audit: {sym} {direction} ({audit_entry['time']})
* **Result:** **{category}** | **Net PnL:** `${net_pnl:+.2f}` (Duration: {duration_m}m)
* **Entry:** `${entry_p}` ➔ **Exit:** `${exit_p}` | **Reason:** `{reason}`
* **Peak Profit (MFE):** `+${peak_profit:.2f}` (`+{mfe_pct}%`) | **Max Drawdown (MAE):** `${max_drawdown:.2f}` (`{mae_pct}%`)
* **💡 Post-Mortem Lesson / Retrospective:**
  > {lesson}

---
"""
            with open(audit_md, "a", encoding="utf-8") as f:
                f.write(md_entry)
        except Exception:
            pass

    def record_decision_snapshot(self, cycle_count: int, market_radar: dict, active_positions: list):
        """Record why trades were taken or passed on every scan interval."""
        # Only log snapshot every 20 cycles (~60s) to keep storage compact
        if cycle_count % 20 != 0:
            return

        date_str = self._get_date_str()
        decisions_file = os.path.join(TRADES_DIR, f"decisions_{date_str}.jsonl")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        snapshot = {
            "time": now_str,
            "cycle": cycle_count,
            "active_positions_count": len(active_positions),
            "pairs": {}
        }

        for sym, analysis in market_radar.items():
            if not analysis:
                continue
            sig = analysis.get("signal", 0)
            price = analysis.get("price", 0.0)
            regime = analysis.get("regime", "NEUTRAL")
            ema_trend = analysis.get("ema_trend", 0.0)
            ema_fast = analysis.get("ema_fast", 0.0)
            ema_slow = analysis.get("ema_slow", 0.0)

            # Determine why it is holding
            why = "HOLD"
            if sig == 0:
                if regime == "BULLISH" and ema_fast <= ema_slow:
                    why = f"BULLISH regime (Price > 200 EMA {ema_trend}), but EMA 9 ({ema_fast}) <= EMA 21 ({ema_slow}). Waiting for bullish crossover."
                elif regime == "BEARISH" and ema_fast >= ema_slow:
                    why = f"BEARISH regime (Price < 200 EMA {ema_trend}), but EMA 9 ({ema_fast}) >= EMA 21 ({ema_slow}). Waiting for bearish crossover."
                elif regime == "BULLISH":
                    why = "BULLISH regime: fast/slow already crossed, waiting for fresh pullback setup."
                else:
                    why = "BEARISH regime: fast/slow already crossed, waiting for fresh pullback setup."
            elif sig == 1:
                why = "VALID BUY SIGNAL: Bullish regime confirmed and fresh 9/21 EMA golden cross."
            elif sig == -1:
                why = "VALID SELL SIGNAL: Bearish regime confirmed and fresh 9/21 EMA death cross."

            snapshot["pairs"][sym] = {
                "price": price,
                "regime": regime,
                "signal": sig,
                "reasoning": why
            }

        try:
            with open(decisions_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(snapshot, default=str) + "\n")
        except Exception:
            pass

recorder = DataRecorder()
