"""
VELOCITY SCALPER: Core Execution Engine & Risk Guardian
Executes high-frequency scanning across 6 crypto pairs,
manages up to MAX_OPEN_POSITIONS concurrent trades with Break-Even locks,
and enforces hard circuit breakers ($3.00 Daily Profit Lock & $3.00 Daily Loss Defense).
"""
import os
import json
import time
import threading
from datetime import datetime, timezone
import pandas as pd
from binance_client import BinanceClient
from strategy import VelocityStrategy
from config import (
    TRADING_MODE, SYMBOLS, DEFAULT_TIMEFRAME, SCAN_INTERVAL_SECONDS,
    STARTING_CAPITAL_USDT, LEVERAGE, ALLOCATED_MARGIN_USDT, MAX_OPEN_POSITIONS,
    DAILY_PROFIT_TARGET_USDT, DAILY_MAX_LOSS_USDT, PARAMS
)
from data_recorder import recorder

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json")

class VelocityEngine:
    def __init__(self):
        self.strategy = VelocityStrategy(PARAMS)
        self.client = BinanceClient(mode="FUTURES")
        self.is_running = True
        self.lock = threading.Lock()
        self.state = self._load_state()
        self.market_radar = {}
        self.logs = []
        self.last_scan_time = None
        self.cycle_count = 0
        self._log(f"Velocity Scalper initialized. Mode: {self.state['trading_mode']} | TF: {DEFAULT_TIMEFRAME} | Max Positions: {MAX_OPEN_POSITIONS} | Target: ${DAILY_PROFIT_TARGET_USDT}/day")

    def _default_state(self):
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "trading_mode": TRADING_MODE,
            "timeframe": DEFAULT_TIMEFRAME,
            "starting_balance": STARTING_CAPITAL_USDT,
            "current_balance": STARTING_CAPITAL_USDT,
            "allocated_margin": ALLOCATED_MARGIN_USDT,
            "max_open_positions": MAX_OPEN_POSITIONS,
            "leverage": LEVERAGE,
            "daily_target": DAILY_PROFIT_TARGET_USDT,
            "daily_max_loss": DAILY_MAX_LOSS_USDT,
            "today_date": today_str,
            "today_realized_pnl": 0.0,
            "today_wins": 0,
            "today_losses": 0,
            "circuit_breaker": "NORMAL", # "NORMAL", "PROFIT_LOCKED", "LOSS_LOCKED"
            "active_positions": [], # Up to MAX_OPEN_POSITIONS concurrent positions
            "active_position": None, # Kept for backwards compatibility
            "closed_trades": []
        }

    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if data.get("today_date") != today_str:
                        # New trading day reset
                        data["today_date"] = today_str
                        data["today_realized_pnl"] = 0.0
                        data["today_wins"] = 0
                        data["today_losses"] = 0
                        data["circuit_breaker"] = "NORMAL"

                    # Migrate active_position -> active_positions list if needed
                    if "active_positions" not in data:
                        data["active_positions"] = []
                        if data.get("active_position"):
                            data["active_positions"].append(data["active_position"])
                    data["max_open_positions"] = MAX_OPEN_POSITIONS
                    return data
            except Exception as e:
                print(f"Error loading state: {e}")
        new_state = self._default_state()
        self._save_state(new_state)
        return new_state

    def _save_state(self, state=None):
        if state is None:
            state = self.state
        # Sync primary active_position pointer for compatibility
        state["active_position"] = state["active_positions"][0] if state.get("active_positions") else None
        state["max_open_positions"] = MAX_OPEN_POSITIONS
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def _log(self, message, level="INFO"):
        now_str = datetime.now().strftime("%H:%M:%S")
        entry = {"time": now_str, "level": level, "msg": message}
        self.logs.append(entry)
        if len(self.logs) > 300:
            self.logs = self.logs[-200:]
        try:
            print(f"[{now_str}] [{level}] {message}", flush=True)
        except (OSError, BrokenPipeError, IOError):
            pass
        try:
            log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.log")
            with open(log_file, "a") as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {message}\n")
        except Exception:
            pass

    def get_status(self):
        with self.lock:
            positions = self.state.get("active_positions", [])
            total_unrealized = sum(p.get("unrealized_pnl", 0.0) for p in positions)
            total_margin = sum(p.get("margin", ALLOCATED_MARGIN_USDT) for p in positions)
            unrealized_pct = (total_unrealized / total_margin * 100) if total_margin > 0 else 0.0

            total_trades = self.state.get("today_wins", 0) + self.state.get("today_losses", 0)
            win_rate = (self.state.get("today_wins", 0) / total_trades * 100) if total_trades > 0 else 0.0

            primary_pos = positions[0] if len(positions) > 0 else None

            now_dt = datetime.now()
            secs_since_scan = (now_dt - self.last_scan_time).total_seconds() if self.last_scan_time else None
            is_loop_healthy = (secs_since_scan is not None and secs_since_scan < 30)

            return {
                "is_running": self.is_running,
                "is_loop_healthy": is_loop_healthy,
                "last_scan_time": self.last_scan_time.strftime("%Y-%m-%d %H:%M:%S") if self.last_scan_time else None,
                "seconds_since_last_scan": round(secs_since_scan, 1) if secs_since_scan is not None else None,
                "trading_mode": self.state.get("trading_mode", "PAPER"),
                "timeframe": self.state.get("timeframe", DEFAULT_TIMEFRAME),
                "starting_balance": self.state.get("starting_balance", 100.0),
                "current_balance": round(self.state.get("current_balance", 100.0), 2),
                "today_realized_pnl": round(self.state.get("today_realized_pnl", 0.0), 2),
                "unrealized_pnl": round(total_unrealized, 2),
                "unrealized_pct": round(unrealized_pct, 2),
                "today_wins": self.state.get("today_wins", 0),
                "today_losses": self.state.get("today_losses", 0),
                "win_rate": round(win_rate, 1),
                "circuit_breaker": self.state.get("circuit_breaker", "NORMAL"),
                "daily_target": self.state.get("daily_target", 3.0),
                "daily_max_loss": self.state.get("daily_max_loss", 3.0),
                "max_open_positions": MAX_OPEN_POSITIONS,
                "active_position": primary_pos,
                "active_positions": positions,
                "market_radar": self.market_radar,
                "recent_trades": self.state.get("closed_trades", [])[-15:],
                "logs": list(reversed(self.logs[-20:]))
            }

    def pause_bot(self):
        with self.lock:
            self.is_running = False
            self._log("Trading engine PAUSED by user.", "WARNING")

    def start_bot(self):
        with self.lock:
            self.is_running = True
            self._log("Trading engine RESUMED by user.", "ACTION")

    def set_timeframe(self, tf):
        with self.lock:
            if tf in ["1m", "3m", "5m", "15m", "1h", "4h"]:
                self.state["timeframe"] = tf
                self._save_state()
                self._log(f"Timeframe set to {tf}", "ACTION")

    def set_trading_mode(self, mode):
        with self.lock:
            if mode in ["PAPER", "LIVE_FUTURES", "LIVE_SPOT"]:
                self.state["trading_mode"] = mode
                self._save_state()
                self._log(f"Trading mode switched to {mode}", "ACTION")

    def emergency_close_active(self, symbol=None):
        with self.lock:
            positions = self.state.get("active_positions", [])
            if not positions:
                return {"success": False, "msg": "No active position to close"}

            to_close = [p for p in positions if (symbol is None or p["symbol"] == symbol)]
            if not to_close:
                return {"success": False, "msg": f"No open position found for {symbol}"}

            closed_symbols = []
            for pos in to_close:
                sym = pos["symbol"]
                current_p = self.market_radar.get(sym, {}).get("price", pos["entry_price"])
                self._close_position(pos, exit_price=current_p, reason="MANUAL_CLOSE")
                closed_symbols.append(sym)
                self._log(f"Manual Emergency Close executed for {sym} at ${current_p}", "WARNING")

            return {"success": True, "msg": f"Closed positions: {', '.join(closed_symbols)}"}

    def _close_position(self, pos, exit_price, reason="TP"):
        sym = pos["symbol"]
        entry_p = pos["entry_price"]
        direction = pos["direction"]
        pos_size = pos["quantity"]
        margin = pos["margin"]
        fee_rate = PARAMS["fee_rate"]

        if direction == "LONG":
            gross_pnl = (exit_price - entry_p) * pos_size
        else:
            gross_pnl = (entry_p - exit_price) * pos_size

        notional = entry_p * pos_size
        fees = notional * fee_rate * 2
        net_pnl = gross_pnl - fees

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry_dt = datetime.strptime(pos["entry_time"], "%Y-%m-%d %H:%M:%S") if "entry_time" in pos else datetime.now()
        duration_mins = round((datetime.now() - entry_dt).total_seconds() / 60, 1)

        closed_record = {
            "symbol": sym,
            "direction": direction,
            "entry_price": entry_p,
            "exit_price": exit_price,
            "quantity": pos_size,
            "margin": margin,
            "gross_pnl": round(gross_pnl, 2),
            "fees": round(fees, 2),
            "net_pnl": round(net_pnl, 2),
            "duration_m": duration_mins,
            "reason": reason,
            "time": now_str
        }

        self.state["closed_trades"].append(closed_record)
        self.state["current_balance"] = round(self.state["current_balance"] + net_pnl, 2)
        self.state["today_realized_pnl"] = round(self.state["today_realized_pnl"] + net_pnl, 2)
        
        if net_pnl > 0:
            self.state["today_wins"] += 1
        else:
            self.state["today_losses"] += 1

        # Remove from active_positions
        self.state["active_positions"] = [p for p in self.state.get("active_positions", []) if p["symbol"] != sym]
        self._save_state()

        # Record trade close with full trajectory and learning audit
        try:
            recorder.record_trade_close(closed_record, pos)
        except Exception:
            pass

        icon = "🎉" if net_pnl > 0 else "🛑"
        self._log(f"{icon} Position Closed: {sym} {direction} | Net: ${net_pnl:+.2f} (Gross ${gross_pnl:+.2f}, Fee ${fees:.2f}) | Reason: {reason} | Duration: {duration_mins}m", "TRADE")

        # Evaluate Circuit Breakers
        daily_pnl = self.state["today_realized_pnl"]
        if daily_pnl >= self.state["daily_target"]:
            self.state["circuit_breaker"] = "PROFIT_LOCKED"
            self._save_state()
            self._log(f"🎯 DAILY TARGET HIT! Today's Realized Profit: ${daily_pnl:+.2f} (Target: ${self.state['daily_target']:.2f}). Trading LOCKED for today to protect profits!", "PROFIT")
        elif daily_pnl <= -self.state["daily_max_loss"]:
            self.state["circuit_breaker"] = "LOSS_LOCKED"
            self._save_state()
            self._log(f"🛡️ CIRCUIT BREAKER DEFENSE TRIGGERED: Daily Loss ${daily_pnl:.2f} reached -$3.00 cap. Bot HALTED for today. $97.00 Capital Safe!", "DEFENSE")

    def _open_position(self, sym, direction, price, sl_price, tp_price, be_trigger):
        sl_dist = abs(price - sl_price)
        risk_usd = PARAMS["risk_per_trade_usd"] # $2.50
        
        pos_size = risk_usd / sl_dist if sl_dist > 0 else (ALLOCATED_MARGIN_USDT * LEVERAGE / price)
        # Cap notional size to margin * leverage ($25 * 10 = $250)
        max_notional = ALLOCATED_MARGIN_USDT * LEVERAGE
        if (price * pos_size) > max_notional:
            pos_size = max_notional / price

        pos_size = round(pos_size, 4)
        margin = round((price * pos_size) / LEVERAGE, 2)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        pos = {
            "symbol": sym,
            "direction": direction,
            "entry_price": price,
            "quantity": pos_size,
            "margin": margin,
            "leverage": LEVERAGE,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "be_trigger": be_trigger,
            "be_locked": False,
            "unrealized_pnl": 0.0,
            "entry_time": now_str
        }

        if "active_positions" not in self.state:
            self.state["active_positions"] = []
            
        self.state["active_positions"].append(pos)
        self._save_state()

        # Record trade open context
        try:
            recorder.record_trade_open(pos, self.market_radar.get(sym, {}))
        except Exception:
            pass

        self._log(f"🚀 NEW POSITION OPENED: {sym} {direction} @ ${price} | Qty: {pos_size} (Margin: ${margin}, 10x) | SL: ${sl_price} | TP: ${tp_price} | Active Positions: {len(self.state['active_positions'])}/{MAX_OPEN_POSITIONS}", "TRADE")

    def scan_cycle(self):
        """Execute one complete scanning and multi-position management loop."""
        try:
            self.cycle_count += 1
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self.state.get("today_date") != today_str:
                self.state["today_date"] = today_str
                self.state["today_realized_pnl"] = 0.0
                self.state["today_wins"] = 0
                self.state["today_losses"] = 0
                self.state["circuit_breaker"] = "NORMAL"
                self._save_state()
                self._log("📅 New Trading Day initiated (UTC 00:00). Daily counters reset.", "INFO")

            # 1. Update Market Radar with isolated per-symbol error handling
            for sym in SYMBOLS:
                try:
                    df = self.client.fetch_klines(sym, interval=DEFAULT_TIMEFRAME, limit=250)
                    analysis = self.strategy.analyze_latest(df)
                    self.market_radar[sym] = analysis
                    # Save real tick and indicator data for future AI training
                    try:
                        recorder.record_tick(sym, analysis.get("price", 0.0), analysis)
                    except Exception:
                        pass
                except Exception as e:
                    self._log(f"Warning: Failed to update radar for {sym}: {e}", "WARNING")

            # 2. Manage All Active Positions (never skipped even if some radar fetches failed)
            try:
                positions = list(self.state.get("active_positions", []))
                for pos in positions:
                    sym = pos["symbol"]
                    curr_info = self.market_radar.get(sym)
                    curr_p = None
                    if curr_info and "price" in curr_info and curr_info["price"] > 0:
                        curr_p = curr_info["price"]
                    else:
                        try:
                            curr_p = self.client.get_ticker_price(sym)
                        except Exception:
                            curr_p = None

                    if curr_p is None:
                        continue

                    entry_p = pos["entry_price"]
                    direction = pos["direction"]
                    pos_size = pos["quantity"]
                    tp_p = pos["tp_price"]
                    be_trigger = pos["be_trigger"]
                    be_locked = pos.get("be_locked", False)

                    # Calculate unrealized PnL
                    if direction == "LONG":
                        unrealized = (curr_p - entry_p) * pos_size
                        # Break-Even check (+1.0R)
                        if not be_locked and curr_p >= be_trigger:
                            new_sl = round(entry_p * (1.0 + PARAMS["be_fee_offset"]), 4)
                            pos["sl_price"] = new_sl
                            pos["be_locked"] = True
                            self._save_state()
                            self._log(f"🛡️ BREAK-EVEN ACTIVATED on {sym} LONG! Stop Loss moved to ${new_sl} (+0.18% locked). Zero risk trade.", "PROFIT")
                        
                        # TP / SL check
                        if curr_p >= tp_p:
                            self._close_position(pos, exit_price=tp_p, reason="TAKE_PROFIT")
                            continue
                        elif curr_p <= pos["sl_price"]:
                            reason = "BREAK_EVEN" if pos.get("be_locked") else "STOP_LOSS"
                            self._close_position(pos, exit_price=pos["sl_price"], reason=reason)
                            continue

                    elif direction == "SHORT":
                        unrealized = (entry_p - curr_p) * pos_size
                        # Break-Even check
                        if not be_locked and curr_p <= be_trigger:
                            new_sl = round(entry_p * (1.0 - PARAMS["be_fee_offset"]), 4)
                            pos["sl_price"] = new_sl
                            pos["be_locked"] = True
                            self._save_state()
                            self._log(f"🛡️ BREAK-EVEN ACTIVATED on {sym} SHORT! Stop Loss moved to ${new_sl} (+0.18% locked). Zero risk trade.", "PROFIT")

                        if curr_p <= tp_p:
                            self._close_position(pos, exit_price=tp_p, reason="TAKE_PROFIT")
                            continue
                        elif curr_p >= pos["sl_price"]:
                            reason = "BREAK_EVEN" if pos.get("be_locked") else "STOP_LOSS"
                            self._close_position(pos, exit_price=pos["sl_price"], reason=reason)
                            continue

                    pos["unrealized_pnl"] = round(unrealized, 2)
                    self._save_state()

                    # Track trade trajectory (MFE, MAE, peak profit, max drawdown)
                    try:
                        recorder.update_trade_trajectory(pos, curr_p)
                    except Exception:
                        pass

                    # Live tick update for active position
                    pnl_sign = "+" if unrealized >= 0 else ""
                    margin_val = pos.get("margin", ALLOCATED_MARGIN_USDT)
                    unrealized_pct = (unrealized / margin_val * 100) if margin_val > 0 else 0.0
                    self._log(
                        f"⚡ LIVE TICK: {sym} {direction} | Price: ${curr_p:,.2f} (Entry: ${entry_p:,.2f}) | PnL: {pnl_sign}${unrealized:,.2f} ({pnl_sign}{unrealized_pct:.2f}%) | SL: ${pos['sl_price']:,.2f} | TP: ${tp_p:,.2f}",
                        "TICK"
                    )
            except Exception as e:
                self._log(f"Position management error: {e}", "ERROR")

            # 3. Check for New Entry Signals if slots are available
            try:
                # Log scan activity across the 6 coins
                pair_summaries = []
                for s in SYMBOLS:
                    info = self.market_radar.get(s, {})
                    sig_lbl = info.get("signal_label", "HOLD")
                    p = info.get("price", 0.0)
                    short_s = s.replace("USDT", "")
                    pair_summaries.append(f"{short_s}: ${p:,.2f} ({sig_lbl})" if p > 0 else f"{short_s}: HOLD")

                active_count = len(self.state.get("active_positions", []))
                self._log(
                    f"🔍 SCAN #{self.cycle_count} (1h) | Slots: {active_count}/{MAX_OPEN_POSITIONS} Active | " + " | ".join(pair_summaries),
                    "SCAN"
                )

                # Record decision rationale snapshot periodically for AI training
                try:
                    recorder.record_decision_snapshot(self.cycle_count, self.market_radar, self.state.get("active_positions", []))
                except Exception:
                    pass

                if not self.is_running:
                    return

                if self.state.get("circuit_breaker") in ["PROFIT_LOCKED", "LOSS_LOCKED"]:
                    return

                current_open = self.state.get("active_positions", [])
                if len(current_open) >= MAX_OPEN_POSITIONS:
                    return

                open_syms = {p["symbol"] for p in current_open}

                # Scan candidate symbols that are NOT currently open
                for sym in SYMBOLS:
                    if sym in open_syms:
                        continue # One trade per coin rule
                    if len(self.state.get("active_positions", [])) >= MAX_OPEN_POSITIONS:
                        break # Max concurrent slots full

                    analysis = self.market_radar.get(sym)
                    if not analysis:
                        continue

                    sig = analysis.get("signal", 0)
                    price = analysis.get("price", 0.0)
                    target_sl = analysis.get("target_sl", 0.0)
                    target_tp = analysis.get("target_tp", 0.0)
                    be_trigger = analysis.get("be_trigger_price", 0.0)

                    if sig == 1: # LONG
                        self._open_position(sym, "LONG", price, target_sl, target_tp, be_trigger)
                        open_syms.add(sym)
                    elif sig == -1: # SHORT
                        self._open_position(sym, "SHORT", price, target_sl, target_tp, be_trigger)
                        open_syms.add(sym)
            except Exception as e:
                self._log(f"Signal evaluation error: {e}", "ERROR")

        except Exception as e:
            self._log(f"Scan loop error: {str(e)}", "ERROR")
        finally:
            self.last_scan_time = datetime.now()

    def run_forever(self):
        """Dedicated background daemon loop with crash-proof self-recovery."""
        self._log("Velocity Execution Daemon running live tick loop...")
        while True:
            try:
                self.scan_cycle()
            except Exception as e:
                try:
                    self._log(f"Execution daemon cycle error: {e}", "ERROR")
                except Exception:
                    pass
                time.sleep(2)
            time.sleep(SCAN_INTERVAL_SECONDS)
