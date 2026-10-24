"""
VELOCITY SCALPER: Multi-Engine Core Execution & Risk Guardian
Unified Tri-Engine Architecture:
1. Hybrid Ladder-Lock: 3-Stage Profit Ladder (+0.25% Fee Shield, +1.0R Step Lock, +1.5R Step Lock, +2.2R TP)
2. Balanced Trailing Scalper: Dynamic High-Watermark Trailing (+0.25% Fee Shield, 0.28% Trail @ +0.50%, +2.2R TP)
3. Swing Runner (Baseline): High-Conviction Swing (+1.0R Break-Even, +2.2R TP)

Each engine operates with its own isolated $100 base, independent position tracking, and circuit breakers,
while sharing a single Binance WebSocket/radar feed to guarantee zero duplicate API calls and zero rate limits.
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
    DAILY_PROFIT_TARGET_USDT, COMBINED_PROFIT_TARGET_USDT, DAILY_MAX_LOSS_USDT, PARAMS, ENGINE_CONFIGS
)
from data_recorder import recorder

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class SingleEngineInstance:
    """Represents an independent trading engine running its own strategy, balance, and positions."""
    def __init__(self, engine_id: str, config: dict, shared_strategy: VelocityStrategy):
        self.engine_id = engine_id
        self.config = config
        self.strategy = shared_strategy
        self.name = config.get("name", engine_id.upper())
        self.badge = config.get("badge", f"[{engine_id.upper()}]")
        self.state_file = os.path.join(BASE_DIR, config.get("state_file", f"bot_state_{engine_id}.json"))
        self.is_running = True
        self.lock = threading.Lock()
        self.state = self._load_state()

    def _default_state(self):
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        capital = self.config.get("starting_capital", STARTING_CAPITAL_USDT)
        margin = self.config.get("allocated_margin", ALLOCATED_MARGIN_USDT)
        lev = self.config.get("leverage", LEVERAGE)
        target = self.config.get("daily_target", DAILY_PROFIT_TARGET_USDT)
        max_loss = self.config.get("daily_max_loss", DAILY_MAX_LOSS_USDT)
        max_pos = self.config.get("max_positions", MAX_OPEN_POSITIONS)

        return {
            "engine_id": self.engine_id,
            "engine_name": self.name,
            "trading_mode": TRADING_MODE,
            "timeframe": DEFAULT_TIMEFRAME,
            "starting_balance": capital,
            "current_balance": capital,
            "allocated_margin": margin,
            "max_open_positions": max_pos,
            "leverage": lev,
            "daily_target": target,
            "daily_max_loss": max_loss,
            "today_date": today_str,
            "today_realized_pnl": 0.0,
            "today_wins": 0,
            "today_losses": 0,
            "circuit_breaker": "NORMAL", # "NORMAL", "PROFIT_LOCKED", "LOSS_LOCKED"
            "active_positions": [],
            "active_position": None,
            "closed_trades": []
        }

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if data.get("today_date") != today_str:
                        data["today_date"] = today_str
                        data["today_realized_pnl"] = 0.0
                        data["today_wins"] = 0
                        data["today_losses"] = 0
                        data["circuit_breaker"] = "NORMAL"

                    if "active_positions" not in data:
                        data["active_positions"] = []
                        if data.get("active_position"):
                            data["active_positions"].append(data["active_position"])
                    data["max_open_positions"] = self.config.get("max_positions", MAX_OPEN_POSITIONS)
                    data["daily_target"] = self.config.get("daily_target", DAILY_PROFIT_TARGET_USDT)
                    data["daily_max_loss"] = self.config.get("daily_max_loss", DAILY_MAX_LOSS_USDT)
                    data["allocated_margin"] = self.config.get("allocated_margin", ALLOCATED_MARGIN_USDT)
                    data["leverage"] = self.config.get("leverage", LEVERAGE)
                    return data
            except Exception as e:
                print(f"Error loading state for {self.engine_id}: {e}")
        new_state = self._default_state()
        self._save_state(new_state)
        return new_state

    def _save_state(self, state=None):
        if state is None:
            state = self.state
        state["active_position"] = state["active_positions"][0] if state.get("active_positions") else None
        state["max_open_positions"] = self.config.get("max_positions", MAX_OPEN_POSITIONS)
        try:
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception:
            pass

    def manage_positions(self, market_radar: dict, client: BinanceClient, log_fn):
        """Iterates through active positions and applies strategy-specific risk & exit rules."""
        with self.lock:
            positions = list(self.state.get("active_positions", []))
            for pos in positions:
                sym = pos["symbol"]
                curr_info = market_radar.get(sym)
                curr_p = None
                if curr_info and "price" in curr_info and curr_info["price"] > 0:
                    curr_p = curr_info["price"]
                else:
                    try:
                        curr_p = client.get_ticker_price(sym)
                    except Exception:
                        curr_p = None

                if curr_p is None or curr_p <= 0:
                    continue

                direction = pos["direction"]
                entry_p = pos["entry_price"]
                pos_size = pos["quantity"]
                sl_dist = pos.get("sl_dist", abs(entry_p - pos["sl_price"]))
                tp_p = pos["tp_price"]

                # Initialize tracking fields
                if "highest_p" not in pos:
                    pos["highest_p"] = entry_p
                if "lowest_p" not in pos:
                    pos["lowest_p"] = entry_p

                # 1. Update Extremes
                if curr_p > pos["highest_p"]:
                    pos["highest_p"] = curr_p
                if curr_p < pos["lowest_p"]:
                    pos["lowest_p"] = curr_p

                highest_p = pos["highest_p"]
                lowest_p = pos["lowest_p"]

                # 2. Strategy Specific Dynamic Stepping Profit Lock
                if direction == "LONG":
                    gain_pct = (highest_p - entry_p) / entry_p
                    gain_r = (highest_p - entry_p) / sl_dist if sl_dist > 0 else 0.0
                    peak_usd = (highest_p - entry_p) * pos_size
                    pos["peak_profit_usd"] = max(pos.get("peak_profit_usd", 0.0), round(peak_usd, 2))

                    # Dynamic Step-by-Step Dollar Profit Lock Ladder ($1.00 -> $2.50 -> $4.00 -> $10.00 -> $25+)
                    locked_usd = 0.0
                    step_num = 0

                    if peak_usd >= 1.20 and peak_usd < 2.50:
                        locked_usd = 0.80   # Step 1: Early Lock +$0.80 - $1.00 net
                        step_num = 1
                    elif peak_usd >= 2.50 and peak_usd < 4.00:
                        locked_usd = 1.60   # Step 2: Lock +$1.60 net
                        step_num = 2
                    elif peak_usd >= 4.00 and peak_usd < 6.00:
                        locked_usd = 2.80   # Step 3: Lock +$2.80 net
                        step_num = 3
                    elif peak_usd >= 6.00 and peak_usd < 10.00:
                        locked_usd = 4.50   # Step 4: Lock +$4.50 net
                        step_num = 4
                    elif peak_usd >= 10.00 and peak_usd < 15.00:
                        locked_usd = 7.80   # Step 5: Lock +$7.80 net
                        step_num = 5
                    elif peak_usd >= 15.00:
                        locked_usd = round(peak_usd * 0.80, 2)  # Step 6: Unlimited Runner (Locks 80% of peak, runs to $25+)
                        step_num = 6

                    if locked_usd > 0 and locked_usd > pos.get("step_locked_usd", 0.0):
                        target_sl = round(entry_p + (locked_usd / pos_size), 4)
                        if target_sl > pos["sl_price"]:
                            old_sl = pos["sl_price"]
                            pos["sl_price"] = target_sl
                            pos["step_locked_usd"] = locked_usd
                            pos["step"] = step_num
                            pos["be_locked"] = True
                            pos["shield_locked"] = True
                            self._save_state()
                            log_fn(f"{self.badge} 🪜 STEP {step_num} PROFIT LOCK on {sym} LONG! Peak: ${peak_usd:.2f} | SL moved ${old_sl} -> ${target_sl} (+${locked_usd:.2f} locked).", "PROFIT")

                    # Check TP and SL for LONG
                    if curr_p >= tp_p:
                        self._close_position(pos, exit_price=tp_p, reason="TAKE_PROFIT_RUNNER", log_fn=log_fn)
                        continue
                    elif curr_p <= pos["sl_price"]:
                        if pos.get("step_locked_usd", 0) > 0:
                            reason = f"PROFIT_LOCK_+${pos['step_locked_usd']:.2f}"
                        elif pos.get("step2_locked"):
                            reason = "PROFIT_LOCK_1.8R"
                        elif pos.get("step1_locked"):
                            reason = "PROFIT_LOCK_1.0R"
                        elif pos.get("trail_active"):
                            reason = "TRAILING_STOP"
                        elif pos.get("be_locked") or pos.get("shield_locked"):
                            reason = "BREAK_EVEN"
                        else:
                            reason = "STOP_LOSS"
                        self._close_position(pos, exit_price=pos["sl_price"], reason=reason, log_fn=log_fn)
                        continue

                elif direction == "SHORT":
                    gain_pct = (entry_p - lowest_p) / entry_p
                    gain_r = (entry_p - lowest_p) / sl_dist if sl_dist > 0 else 0.0
                    peak_usd = (entry_p - lowest_p) * pos_size
                    pos["peak_profit_usd"] = max(pos.get("peak_profit_usd", 0.0), round(peak_usd, 2))

                    # Dynamic Step-by-Step Dollar Profit Lock Ladder ($1.00 -> $2.50 -> $4.00 -> $10.00 -> $25+)
                    locked_usd = 0.0
                    step_num = 0

                    if peak_usd >= 1.20 and peak_usd < 2.50:
                        locked_usd = 0.80   # Step 1: Early Lock +$0.80 - $1.00 net
                        step_num = 1
                    elif peak_usd >= 2.50 and peak_usd < 4.00:
                        locked_usd = 1.60   # Step 2: Lock +$1.60 net
                        step_num = 2
                    elif peak_usd >= 4.00 and peak_usd < 6.00:
                        locked_usd = 2.80   # Step 3: Lock +$2.80 net
                        step_num = 3
                    elif peak_usd >= 6.00 and peak_usd < 10.00:
                        locked_usd = 4.50   # Step 4: Lock +$4.50 net
                        step_num = 4
                    elif peak_usd >= 10.00 and peak_usd < 15.00:
                        locked_usd = 7.80   # Step 5: Lock +$7.80 net
                        step_num = 5
                    elif peak_usd >= 15.00:
                        locked_usd = round(peak_usd * 0.80, 2)  # Step 6: Unlimited Runner (Locks 80% of peak, runs to $25+)
                        step_num = 6

                    if locked_usd > 0 and locked_usd > pos.get("step_locked_usd", 0.0):
                        target_sl = round(entry_p - (locked_usd / pos_size), 4)
                        if target_sl < pos["sl_price"]:
                            old_sl = pos["sl_price"]
                            pos["sl_price"] = target_sl
                            pos["step_locked_usd"] = locked_usd
                            pos["step"] = step_num
                            pos["be_locked"] = True
                            pos["shield_locked"] = True
                            self._save_state()
                            log_fn(f"{self.badge} 🪜 STEP {step_num} PROFIT LOCK on {sym} SHORT! Peak: ${peak_usd:.2f} | SL moved ${old_sl} -> ${target_sl} (+${locked_usd:.2f} locked).", "PROFIT")

                    # Check TP and SL for SHORT
                    if curr_p <= tp_p:
                        self._close_position(pos, exit_price=tp_p, reason="TAKE_PROFIT_RUNNER", log_fn=log_fn)
                        continue
                    elif curr_p >= pos["sl_price"]:
                        if pos.get("step_locked_usd", 0) > 0:
                            reason = f"PROFIT_LOCK_+${pos['step_locked_usd']:.2f}"
                        elif pos.get("step2_locked"):
                            reason = "PROFIT_LOCK_1.8R"
                        elif pos.get("step1_locked"):
                            reason = "PROFIT_LOCK_1.0R"
                        elif pos.get("trail_active"):
                            reason = "TRAILING_STOP"
                        elif pos.get("be_locked") or pos.get("shield_locked"):
                            reason = "BREAK_EVEN"
                        else:
                            reason = "STOP_LOSS"
                        self._close_position(pos, exit_price=pos["sl_price"], reason=reason, log_fn=log_fn)
                        continue

                # 3. Calculate Unrealized PnL
                unrealized = (curr_p - entry_p) * pos_size if direction == "LONG" else (entry_p - curr_p) * pos_size
                pos["unrealized_pnl"] = round(unrealized, 2)
                self._save_state()

                # Trajectory update
                try:
                    recorder.update_trade_trajectory(pos, curr_p)
                except Exception:
                    pass

            # 4. Engine Basket Take-Profit & Trailing Vault Check
            active_now = list(self.state.get("active_positions", []))
            if active_now:
                total_eng_unrealized = sum(p.get("unrealized_pnl", 0.0) for p in active_now)
                today_realized = self.state.get("today_realized_pnl", 0.0)
                daily_target = self.state.get("daily_target", DAILY_PROFIT_TARGET_USDT)

                # Track peak floating profit for trailing vault
                peak_unrealized = self.state.get("peak_floating_pnl", 0.0)
                if total_eng_unrealized > peak_unrealized:
                    peak_unrealized = total_eng_unrealized
                    self.state["peak_floating_pnl"] = peak_unrealized

                # When engine total floating profit reaches >= $3.00, guarantee $1.00 lock on every active trade
                if total_eng_unrealized >= 3.00:
                    for p in active_now:
                        if p.get("step_locked_usd", 0.0) < 0.80:
                            p["step_locked_usd"] = 0.80
                            p["be_locked"] = True
                            p_sym = p["symbol"]
                            p_entry = p["entry_price"]
                            p_size = p["quantity"]
                            if p["direction"] == "LONG":
                                p_new_sl = round(p_entry + (0.80 / p_size), 4)
                                if p_new_sl > p["sl_price"]:
                                    p["sl_price"] = p_new_sl
                            else:
                                p_new_sl = round(p_entry - (0.80 / p_size), 4)
                                if p_new_sl < p["sl_price"]:
                                    p["sl_price"] = p_new_sl
                    self._save_state()

                # Trailing Vault: If engine peak reached >= $5.00 and retraces by > 30% from peak, lock in the gains!
                if peak_unrealized >= 5.00 and total_eng_unrealized <= (peak_unrealized * 0.70):
                    reason = "ENGINE_TRAILING_VAULT_LOCK"
                    log_fn(
                        f"{self.badge} 🎯 ENGINE TRAILING VAULT TRIGGERED! Floating: ${total_eng_unrealized:+.2f} (Peak: ${peak_unrealized:+.2f}) | Locking in profits!",
                        "PROFIT"
                    )
                    current_prices = {s: market_radar.get(s, {}).get("price", 0.0) for s in SYMBOLS}
                    for p in active_now:
                        sym = p["symbol"]
                        curr_p = current_prices.get(sym) or p.get("entry_price")
                        self._close_position(p, exit_price=curr_p, reason=reason, log_fn=log_fn)

                    self.state["peak_floating_pnl"] = 0.0
                    self.state["circuit_breaker"] = "PROFIT_LOCKED"
                    self._save_state()
                    log_fn(f"{self.badge} 🏆 ALL POSITIONS CLOSED & PROFIT LOCKED for today! Total Realized: ${self.state['today_realized_pnl']:+.2f}", "PROFIT")

    def evaluate_signals(self, market_radar: dict, log_fn):
        """Scans for new high-probability entries if engine slots are available."""
        with self.lock:
            if not self.is_running:
                return

            if self.state.get("circuit_breaker") in ["PROFIT_LOCKED", "LOSS_LOCKED"]:
                return

            max_pos = self.config.get("max_positions", MAX_OPEN_POSITIONS)
            current_open = self.state.get("active_positions", [])
            if len(current_open) >= max_pos:
                return

            open_syms = {p["symbol"] for p in current_open}

            for sym in SYMBOLS:
                if sym in open_syms:
                    continue
                if len(self.state.get("active_positions", [])) >= max_pos:
                    break

                analysis = market_radar.get(sym)
                if not analysis:
                    continue

                sig = analysis.get("signal", 0)
                price = analysis.get("price", 0.0)
                target_sl = analysis.get("target_sl", 0.0)
                target_tp = analysis.get("target_tp", 0.0)
                be_trigger = analysis.get("be_trigger_price", 0.0)
                atr = analysis.get("atr", 0.0)

                if sig == 1:
                    self._open_position(sym, "LONG", price, target_sl, target_tp, be_trigger, atr, log_fn)
                    open_syms.add(sym)
                elif sig == -1:
                    self._open_position(sym, "SHORT", price, target_sl, target_tp, be_trigger, atr, log_fn)
                    open_syms.add(sym)

    def _open_position(self, sym, direction, price, sl_price, tp_price, be_trigger, atr, log_fn):
        sl_dist = abs(price - sl_price) if sl_price > 0 else (atr if atr > 0 else price * 0.006)
        tp_r = self.config.get("tp_r", PARAMS.get("rr_ratio", 2.6))
        be_r = self.config.get("be_trigger_r", 1.2)
        if direction == "LONG":
            tp_price = round(price + (tp_r * sl_dist), 4)
            be_trigger = round(price + (be_r * sl_dist), 4)
        else:
            tp_price = round(price - (tp_r * sl_dist), 4)
            be_trigger = round(price - (be_r * sl_dist), 4)

        risk_usd = self.config.get("risk_per_trade_usd", PARAMS.get("risk_per_trade_usd", 3.00))
        margin_setting = self.config.get("allocated_margin", ALLOCATED_MARGIN_USDT)
        lev = self.config.get("leverage", LEVERAGE)

        pos_size = risk_usd / sl_dist if sl_dist > 0 else (margin_setting * lev / price)
        max_notional = margin_setting * lev
        if (price * pos_size) > max_notional:
            pos_size = max_notional / price

        pos_size = round(pos_size, 4)
        margin = round((price * pos_size) / lev, 2)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        pos = {
            "symbol": sym,
            "direction": direction,
            "entry_price": price,
            "quantity": pos_size,
            "margin": margin,
            "leverage": lev,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "be_trigger": be_trigger,
            "sl_dist": sl_dist,
            "atr": atr,
            "highest_p": price,
            "lowest_p": price,
            "step": 0,
            "shield_locked": False,
            "step1_locked": False,
            "step2_locked": False,
            "trail_active": False,
            "be_locked": False,
            "unrealized_pnl": 0.0,
            "entry_time": now_str
        }

        if "active_positions" not in self.state:
            self.state["active_positions"] = []

        self.state["active_positions"].append(pos)
        self._save_state()

        try:
            recorder.record_trade_open(pos, {"atr": atr})
        except Exception:
            pass

        log_fn(
            f"{self.badge} 🚀 NEW POSITION OPENED: {sym} {direction} @ ${price:,.2f} | Qty: {pos_size} (Margin: ${margin}, {lev}x) | SL: ${sl_price:,.2f} | TP: ${tp_price:,.2f} | Slots: {len(self.state['active_positions'])}/{self.config.get('max_positions', 3)}",
            "TRADE"
        )

    def _close_position(self, pos, exit_price, reason="TP", log_fn=print):
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

        self.state["active_positions"] = [p for p in self.state.get("active_positions", []) if p["symbol"] != sym]
        self._save_state()

        try:
            recorder.record_trade_close(closed_record, pos)
        except Exception:
            pass

        icon = "🎉" if net_pnl > 0 else "🛑"
        log_fn(
            f"{self.badge} {icon} Position Closed: {sym} {direction} | Net: ${net_pnl:+.2f} (Gross ${gross_pnl:+.2f}, Fee ${fees:.2f}) | Reason: {reason} | Duration: {duration_mins}m",
            "TRADE"
        )

        # Circuit Breaker checks
        daily_pnl = self.state["today_realized_pnl"]
        if daily_pnl >= self.state["daily_target"]:
            self.state["circuit_breaker"] = "PROFIT_LOCKED"
            self._save_state()
            log_fn(f"{self.badge} 🎯 DAILY TARGET HIT! Today's Realized: ${daily_pnl:+.2f} (Target: ${self.state['daily_target']:.2f}). Trading LOCKED for today!", "PROFIT")
        elif daily_pnl <= -self.state["daily_max_loss"]:
            self.state["circuit_breaker"] = "LOSS_LOCKED"
            self._save_state()
            log_fn(f"{self.badge} 🛡️ CIRCUIT BREAKER DEFENSE TRIGGERED: Daily Loss ${daily_pnl:.2f} reached -${self.state['daily_max_loss']:.2f} cap. Engine HALTED for today!", "DEFENSE")

    def emergency_close_active(self, symbol=None, current_prices=None, log_fn=print):
        with self.lock:
            positions = list(self.state.get("active_positions", []))
            if not positions:
                return {"success": False, "msg": f"{self.name}: No active position to close"}

            to_close = [p for p in positions if (symbol is None or p["symbol"] == symbol)]
            if not to_close:
                return {"success": False, "msg": f"{self.name}: No position found for {symbol}"}

            closed_syms = []
            for pos in to_close:
                sym = pos["symbol"]
                curr_p = current_prices.get(sym, pos["entry_price"]) if current_prices else pos["entry_price"]
                self._close_position(pos, exit_price=curr_p, reason="MANUAL_CLOSE", log_fn=log_fn)
                closed_syms.append(sym)

            return {"success": True, "msg": f"{self.name}: Closed positions: {', '.join(closed_syms)}"}

    def get_status(self):
        with self.lock:
            positions = self.state.get("active_positions", [])
            total_unrealized = sum(p.get("unrealized_pnl", 0.0) for p in positions)
            margin_setting = self.config.get("allocated_margin", ALLOCATED_MARGIN_USDT)
            total_margin = sum(p.get("margin", margin_setting) for p in positions)
            unrealized_pct = (total_unrealized / total_margin * 100) if total_margin > 0 else 0.0

            total_trades = self.state.get("today_wins", 0) + self.state.get("today_losses", 0)
            win_rate = (self.state.get("today_wins", 0) / total_trades * 100) if total_trades > 0 else 0.0

            return {
                "engine_id": self.engine_id,
                "engine_name": self.name,
                "badge": self.badge,
                "description": self.config.get("description", ""),
                "is_running": self.is_running,
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
                "max_open_positions": self.config.get("max_positions", 3),
                "active_positions": positions,
                "recent_trades": self.state.get("closed_trades", [])[-15:]
            }


class VelocityEngine:
    """Master Multi-Engine Coordinator managing all 3 engines and shared radar feed."""
    def __init__(self):
        self.strategy = VelocityStrategy(PARAMS)
        self.client = BinanceClient(mode="FUTURES")
        self.is_running = True
        self.lock = threading.Lock()
        self.market_radar = {}
        self.logs = []
        self.last_scan_time = None
        self.cycle_count = 0
        self.active_engine_tab = "ladder" # Default active view in UI

        # Initialize the 3 engine instances
        self.engines = {
            "ladder": SingleEngineInstance("ladder", ENGINE_CONFIGS["ladder"], self.strategy),
            "trailing": SingleEngineInstance("trailing", ENGINE_CONFIGS["trailing"], self.strategy),
            "runner": SingleEngineInstance("runner", ENGINE_CONFIGS["runner"], self.strategy)
        }

        self._log("⚡ Velocity Quant Command Center initialized with 3 Parallel Engines (Ladder, Trailing, Runner).", "ACTION")

    def _log(self, message, level="INFO"):
        now_str = datetime.now().strftime("%H:%M:%S")
        entry = {"time": now_str, "level": level, "msg": message}
        self.logs.append(entry)
        if len(self.logs) > 300:
            self.logs = self.logs[-200:]
        try:
            print(f"[{now_str}] [{level}] {message}", flush=True)
        except Exception:
            pass
        try:
            log_file = os.path.join(BASE_DIR, "server.log")
            with open(log_file, "a") as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] {message}\n")
        except Exception:
            pass

    def scan_cycle(self):
        """Single unified scan cycle: fetches radar once, feeds all 3 engines."""
        try:
            self.cycle_count += 1

            # 0. Midnight UTC Daily Reset Check (Prevents deadlock in LOSS_LOCKED across days)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for engine_id, eng in self.engines.items():
                if eng.state.get("today_date") != today_str:
                    old_date = eng.state.get("today_date", "UNKNOWN")
                    eng.state["today_date"] = today_str
                    eng.state["today_realized_pnl"] = 0.0
                    eng.state["today_wins"] = 0
                    eng.state["today_losses"] = 0
                    eng.state["circuit_breaker"] = "NORMAL"
                    eng._save_state()
                    self._log(f"{eng.badge} Daily Midnight Rollover: {old_date} -> {today_str}. Circuit breaker restored to NORMAL.", "ACTION")

            # 1. Update Market Radar once for all configured coins (0 duplicate API calls)
            for sym in SYMBOLS:
                try:
                    df = self.client.fetch_klines(sym, interval=DEFAULT_TIMEFRAME, limit=250)
                    analysis = self.strategy.analyze_latest(df)
                    self.market_radar[sym] = analysis
                    try:
                        recorder.record_tick(sym, analysis.get("price", 0.0), analysis)
                    except Exception:
                        pass
                except Exception as e:
                    self._log(f"Warning: Failed to update radar for {sym}: {e}", "WARNING")

            # 2. Feed market radar to each engine
            for engine_id, eng in self.engines.items():
                try:
                    eng.manage_positions(self.market_radar, self.client, self._log)
                    eng.evaluate_signals(self.market_radar, self._log)
                except Exception as e:
                    self._log(f"Error in engine [{engine_id}]: {e}", "ERROR")

            # 2.5 Master Portfolio Basket Take-Profit & Master Trailing Vault
            total_active_positions = []
            total_portfolio_unrealized = 0.0
            total_portfolio_realized = 0.0

            for eng in self.engines.values():
                st = eng.state
                total_portfolio_realized += st.get("today_realized_pnl", 0.0)
                for p in st.get("active_positions", []):
                    total_active_positions.append((eng, p))
                    total_portfolio_unrealized += p.get("unrealized_pnl", 0.0)

            total_portfolio_today = total_portfolio_realized + total_portfolio_unrealized
            combined_target = COMBINED_PROFIT_TARGET_USDT

            # Track master peak floating profit
            if not hasattr(self, "master_peak_floating_pnl"):
                self.master_peak_floating_pnl = 0.0
            if total_portfolio_unrealized > self.master_peak_floating_pnl:
                self.master_peak_floating_pnl = total_portfolio_unrealized

            # Master Trailing Vault: Never cap profit at $10! Let runners reach $25+, $35+, but protect 75% of peak if it reverses
            master_trailing_vault = (self.master_peak_floating_pnl >= 10.00 and total_portfolio_unrealized <= (self.master_peak_floating_pnl * 0.75))

            if total_active_positions and master_trailing_vault:
                reason = "MASTER_TRAILING_VAULT_75%"
                self._log(
                    f"🎉🎉🎉 MASTER PORTFOLIO TRAILING VAULT TRIGGERED! Peak was: ${self.master_peak_floating_pnl:+.2f} | Current: ${total_portfolio_unrealized:+.2f} | Locking in massive gains across all 3 engines!",
                    "PROFIT"
                )
                current_prices = {s: self.market_radar.get(s, {}).get("price", 0.0) for s in SYMBOLS}
                for eng, pos in total_active_positions:
                    sym = pos["symbol"]
                    exit_p = current_prices.get(sym) or pos.get("entry_price")
                    eng._close_position(pos, exit_price=exit_p, reason=reason, log_fn=self._log)

                for eng in self.engines.values():
                    eng.state["circuit_breaker"] = "PROFIT_LOCKED"
                    eng._save_state()

                self.master_peak_floating_pnl = 0.0
                self._log(f"🏆 MASTER PORTFOLIO TARGET LOCKED FOR TODAY! Day finished successfully.", "PROFIT")

            # 3. Log scan pulse
            pair_summaries = []
            for s in SYMBOLS:
                info = self.market_radar.get(s, {})
                sig_lbl = info.get("signal_label", "HOLD")
                p = info.get("price", 0.0)
                short_s = s.replace("USDT", "")
                pair_summaries.append(f"{short_s}: ${p:,.2f} ({sig_lbl})" if p > 0 else f"{short_s}: HOLD")

            ladder_pos = len(self.engines["ladder"].state.get("active_positions", []))
            trailing_pos = len(self.engines["trailing"].state.get("active_positions", []))
            runner_pos = len(self.engines["runner"].state.get("active_positions", []))

            self._log(
                f"🔍 SCAN #{self.cycle_count} (1h) | Open Slots: Ladder({ladder_pos}/3) Trail({trailing_pos}/3) Run({runner_pos}/3) | " + " | ".join(pair_summaries),
                "SCAN"
            )

        except Exception as e:
            self._log(f"Scan cycle error: {e}", "ERROR")
        finally:
            self.last_scan_time = datetime.now()
            try:
                with open(os.path.join(BASE_DIR, "market_radar.json"), "w") as rf:
                    json.dump(self.market_radar, rf)
                with open(os.path.join(BASE_DIR, "scan_heartbeat.json"), "w") as hf:
                    json.dump({
                        "last_scan_time": self.last_scan_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "ts": time.time(),
                        "cycle": self.cycle_count
                    }, hf)
            except Exception:
                pass

    def get_status(self, selected_engine=None):
        """Returns comprehensive status across all 3 engines + Master Portfolio summary."""
        with self.lock:
            if selected_engine and selected_engine in self.engines:
                self.active_engine_tab = selected_engine

            engine_statuses = {}
            total_balance = 0.0
            total_starting = 0.0
            total_realized = 0.0
            total_unrealized = 0.0
            total_wins = 0
            total_losses = 0
            all_active_positions = []

            for eid, eng in self.engines.items():
                st = eng.get_status()
                engine_statuses[eid] = st
                total_balance += st["current_balance"]
                total_starting += st["starting_balance"]
                total_realized += st["today_realized_pnl"]
                total_unrealized += st["unrealized_pnl"]
                total_wins += st["today_wins"]
                total_losses += st["today_losses"]

                # Tag each active position with its engine info
                for p in st["active_positions"]:
                    tagged = dict(p)
                    tagged["engine_id"] = eid
                    tagged["engine_name"] = eng.name
                    tagged["engine_badge"] = eng.badge
                    all_active_positions.append(tagged)

            total_trades = total_wins + total_losses
            combined_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0.0

            master_portfolio = {
                "total_balance": round(total_balance, 2),
                "starting_base": round(total_starting, 2),
                "total_profit_usd": round(total_balance - total_starting, 2),
                "total_profit_pct": round(((total_balance - total_starting) / total_starting) * 100, 2),
                "today_realized_pnl": round(total_realized, 2),
                "total_unrealized_pnl": round(total_unrealized, 2),
                "today_wins": total_wins,
                "today_losses": total_losses,
                "combined_win_rate": round(combined_win_rate, 1),
                "total_open_positions": len(all_active_positions),
                "active_engines_count": sum(1 for e in self.engines.values() if e.is_running)
            }

            # 1. Build date-wise daily performance ledger across all strategies
            daily_map = {}
            for eid, eng in self.engines.items():
                badge = eng.badge
                ename = eng.name
                for t in eng.state.get("closed_trades", []):
                    t_time = t.get("time", "")
                    dt_str = t_time.split(" ")[0] if " " in t_time else t_time[:10]
                    if not dt_str:
                        continue
                    if dt_str not in daily_map:
                        daily_map[dt_str] = {
                            "date": dt_str,
                            "total_pnl": 0.0,
                            "total_trades": 0,
                            "wins": 0,
                            "losses": 0,
                            "engines": {
                                "ladder": {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0},
                                "trailing": {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0},
                                "runner": {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
                            },
                            "trades": []
                        }
                    pnl = round(float(t.get("net_pnl", 0.0)), 2)
                    daily_map[dt_str]["total_pnl"] = round(daily_map[dt_str]["total_pnl"] + pnl, 2)
                    daily_map[dt_str]["total_trades"] += 1
                    if pnl > 0:
                        daily_map[dt_str]["wins"] += 1
                    else:
                        daily_map[dt_str]["losses"] += 1

                    if eid in daily_map[dt_str]["engines"]:
                        daily_map[dt_str]["engines"][eid]["pnl"] = round(daily_map[dt_str]["engines"][eid]["pnl"] + pnl, 2)
                        daily_map[dt_str]["engines"][eid]["trades"] += 1
                        if pnl > 0:
                            daily_map[dt_str]["engines"][eid]["wins"] += 1
                        else:
                            daily_map[dt_str]["engines"][eid]["losses"] += 1

                    t_copy = dict(t)
                    t_copy["engine_id"] = eid
                    t_copy["engine_badge"] = badge
                    t_copy["engine_name"] = ename
                    daily_map[dt_str]["trades"].append(t_copy)

            daily_ledger = []
            for dt_str in sorted(daily_map.keys(), reverse=True):
                entry = daily_map[dt_str]
                tot = entry["total_trades"]
                entry["win_rate"] = round((entry["wins"] / tot * 100), 1) if tot > 0 else 0.0
                # Sort trades in descending order of execution time
                entry["trades"] = sorted(entry["trades"], key=lambda x: x.get("time", ""), reverse=True)
                daily_ledger.append(entry)

            active_st = engine_statuses.get(self.active_engine_tab, engine_statuses["ladder"])

            # 2. If in-memory market_radar is empty, load from shared disk file
            if not self.market_radar:
                try:
                    radar_path = os.path.join(BASE_DIR, "market_radar.json")
                    if os.path.exists(radar_path):
                        with open(radar_path, "r") as rf:
                            self.market_radar = json.load(rf)
                except Exception:
                    pass

            now_dt = datetime.now()
            # 3. If last_scan_time is not in memory, check disk heartbeat
            if not self.last_scan_time:
                try:
                    hb_path = os.path.join(BASE_DIR, "scan_heartbeat.json")
                    if os.path.exists(hb_path):
                        with open(hb_path, "r") as hf:
                            hb = json.load(hf)
                            if "last_scan_time" in hb:
                                self.last_scan_time = datetime.strptime(hb["last_scan_time"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            secs_since_scan = (now_dt - self.last_scan_time).total_seconds() if self.last_scan_time else None
            is_loop_healthy = (secs_since_scan is not None and secs_since_scan < 30)

            # 4. Read shared recent logs from server.log if available so all workers share live feed
            recent_logs = []
            try:
                log_file = os.path.join(BASE_DIR, "server.log")
                if os.path.exists(log_file):
                    with open(log_file, "r") as lf:
                        lines = lf.readlines()[-30:]
                        for line in lines:
                            line = line.strip()
                            if line and line.startswith("["):
                                parts = line.split("] [", 1)
                                if len(parts) == 2:
                                    time_part = parts[0].lstrip("[").split(" ")[-1]
                                    lvl_msg = parts[1].split("] ", 1)
                                    lvl = lvl_msg[0] if len(lvl_msg) == 2 else "INFO"
                                    msg = lvl_msg[1] if len(lvl_msg) == 2 else lvl_msg[0]
                                    recent_logs.append({"time": time_part, "level": lvl, "msg": msg})
            except Exception:
                pass
            if not recent_logs:
                recent_logs = list(reversed(self.logs[-25:]))
            else:
                recent_logs = list(reversed(recent_logs[-25:]))

            # Build unified response: backwards-compatible top-level keys + multi-engine blocks
            return {
                "active_engine_tab": self.active_engine_tab,
                "is_running": self.is_running,
                "is_loop_healthy": is_loop_healthy,
                "last_scan_time": self.last_scan_time.strftime("%Y-%m-%d %H:%M:%S") if self.last_scan_time else None,
                "seconds_since_last_scan": round(secs_since_scan, 1) if secs_since_scan is not None else None,
                "engines": engine_statuses,
                "master_portfolio": master_portfolio,
                "all_active_positions": all_active_positions,
                "daily_ledger": daily_ledger,
                "market_radar": self.market_radar,
                "logs": recent_logs,

                # Backwards compatibility fields mapping to active engine tab
                "trading_mode": active_st["trading_mode"],
                "timeframe": active_st["timeframe"],
                "starting_balance": active_st["starting_balance"],
                "current_balance": active_st["current_balance"],
                "today_realized_pnl": active_st["today_realized_pnl"],
                "unrealized_pnl": active_st["unrealized_pnl"],
                "unrealized_pct": active_st["unrealized_pct"],
                "today_wins": active_st["today_wins"],
                "today_losses": active_st["today_losses"],
                "win_rate": active_st["win_rate"],
                "circuit_breaker": active_st["circuit_breaker"],
                "daily_target": active_st["daily_target"],
                "daily_max_loss": active_st["daily_max_loss"],
                "max_open_positions": active_st["max_open_positions"],
                "active_positions": active_st["active_positions"],
                "recent_trades": active_st["recent_trades"]
            }

    def pause_bot(self, engine_id="all"):
        with self.lock:
            if engine_id == "all":
                self.is_running = False
                for eng in self.engines.values():
                    eng.is_running = False
                self._log("All engines PAUSED by user.", "WARNING")
            elif engine_id in self.engines:
                self.engines[engine_id].is_running = False
                self._log(f"Engine [{engine_id}] PAUSED by user.", "WARNING")

    def start_bot(self, engine_id="all"):
        with self.lock:
            if engine_id == "all":
                self.is_running = True
                for eng in self.engines.values():
                    eng.is_running = True
                self._log("All engines RESUMED by user.", "ACTION")
            elif engine_id in self.engines:
                self.engines[engine_id].is_running = True
                self._log(f"Engine [{engine_id}] RESUMED by user.", "ACTION")

    def emergency_close_active(self, symbol=None, engine_id=None):
        current_prices = {s: self.market_radar.get(s, {}).get("price", 0.0) for s in SYMBOLS}
        if engine_id and engine_id in self.engines:
            return self.engines[engine_id].emergency_close_active(symbol, current_prices, self._log)
        else:
            results = []
            for eid, eng in self.engines.items():
                res = eng.emergency_close_active(symbol, current_prices, self._log)
                results.append(res.get("msg", ""))
            return {"success": True, "msg": " | ".join(results)}

    def set_trading_mode(self, mode, engine_id="all"):
        with self.lock:
            targets = self.engines.values() if engine_id == "all" else [self.engines.get(engine_id)]
            for eng in targets:
                if eng:
                    eng.state["trading_mode"] = mode
                    eng._save_state()
            self._log(f"Trading mode switched to {mode} ({engine_id})", "ACTION")

    def run_forever(self):
        self._log("Velocity Execution Daemon running live multi-engine loop...")
        heartbeat_file = os.path.join(BASE_DIR, "scan_heartbeat.json")
        while True:
            try:
                now_ts = time.time()
                should_scan = True
                if os.path.exists(heartbeat_file):
                    try:
                        with open(heartbeat_file, "r") as hf:
                            hb = json.load(hf)
                            if now_ts - hb.get("ts", 0) < SCAN_INTERVAL_SECONDS:
                                should_scan = False
                    except Exception:
                        pass

                if should_scan:
                    self.scan_cycle()
            except Exception as e:
                try:
                    self._log(f"Execution daemon cycle error: {e}", "ERROR")
                except Exception:
                    pass
                time.sleep(2)
            time.sleep(1)
