"""
VELOCITY SCALPER: Configuration & Quantitative Parameters
Tailored for $100 Account Aggressive Micro-Scalping (Target: $2.00 - $3.00 / day)
"""
import os

ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def load_env():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

load_env()

# --- TRADING EXECUTION MODE ---
# "PAPER" (Ultra-accurate real-tick sim), "LIVE_FUTURES", "LIVE_SPOT"
TRADING_MODE = os.getenv("TRADING_MODE", "PAPER")
ENVIRONMENT = os.getenv("ENVIRONMENT", "TESTNET")

# --- BINANCE CREDENTIALS ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_FUTURES_API_KEY = os.getenv("BINANCE_FUTURES_API_KEY", "")
BINANCE_FUTURES_API_SECRET = os.getenv("BINANCE_FUTURES_API_SECRET", "")

# Base Endpoints
SPOT_LIVE_URL = "https://api.binance.com"
SPOT_TESTNET_URL = "https://testnet.binance.vision"
FUTURES_LIVE_URL = "https://fapi.binance.com"
FUTURES_TESTNET_URL = "https://testnet.binancefuture.com"

# --- SCALPING UNIVERSE & TIMEFRAME ---
# 6 Major Stable Cryptos with deep liquidity and proven 72%+ win rate
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT"]
DEFAULT_TIMEFRAME = "1h"  # 1-hour verified multi-pair swing engine (3-4 high-conviction trades/day)
SCAN_INTERVAL_SECONDS = 3 # 3-second live scan cycle

# --- CAPITAL & POSITION SIZING ---
STARTING_CAPITAL_USDT = float(os.getenv("STARTING_CAPITAL_USDT", "100.0"))
LEVERAGE = int(os.getenv("LEVERAGE", "10"))                  # 10x isolated leverage
ALLOCATED_MARGIN_USDT = float(os.getenv("ALLOCATED_MARGIN_USDT", "25.0")) # $25 margin per trade ($75 max across 3 trades)
MAX_OPEN_POSITIONS = 3 # Up to 3 concurrent positions across distinct crypto pairs

# --- STRICT DAILY CIRCUIT BREAKERS ---
DAILY_PROFIT_TARGET_USDT = float(os.getenv("DAILY_PROFIT_TARGET_USDT", "3.00")) # User Target: $2.00 - $3.00 / day
DAILY_MAX_LOSS_USDT = float(os.getenv("DAILY_MAX_LOSS_USDT", "3.00"))           # Stop trading if -$3.00 daily loss hits
MAX_CONSECUTIVE_LOSSES = 2
COOLDOWN_MINUTES = 30

# --- QUANTITATIVE GUARDIAN PARAMETERS ---
PARAMS = {
    "ema_fast": 9,
    "ema_slow": 21,
    "ema_trend": 200,        # Trend filter: BUY if Price > 200 EMA, SHORT if Price < 200 EMA
    "atr_period": 14,
    "sl_atr_mult": 1.0,      # Stop Loss distance = 1.0 * ATR
    "rr_ratio": 2.2,         # Take Profit = 2.2 * Risk
    "be_trigger_r": 1.0,     # Move SL to Break-Even once profit reaches +1.0R
    "be_fee_offset": 0.0018, # +0.18% to guarantee net profit after fees
    "risk_per_trade_usd": 2.50, # $2.50 risk per trade
    "max_trade_duration_bars": 36, # Time exit after 3 hours if stagnant
    "fee_rate": 0.0004       # 0.04% taker fee per leg (0.08% roundtrip)
}

# --- TRI-ENGINE QUANTITATIVE CONFIGURATIONS ---
ENGINE_CONFIGS = {
    "ladder": {
        "id": "ladder",
        "name": "Hybrid Ladder-Lock",
        "badge": "🛡️ LADDER",
        "description": "3-Stage Profit Ladder: +0.25% Fee Shield, +1.0R Step Lock, +1.5R Step Lock, +2.2R TP",
        "starting_capital": 100.0,
        "allocated_margin": 25.0,
        "leverage": 5,
        "max_positions": 3,
        "daily_target": 3.0,
        "daily_max_loss": 3.0,
        "early_be_trigger_pct": 0.0025, # +0.25% profit triggers early BE
        "fee_shield_offset": 0.0010,     # +0.10% lock (guarantees net green exit after fees)
        "step_1_r_trigger": 1.0,         # +1.0R profit triggers step 1
        "step_1_r_lock": 0.40,           # lock at +0.40R
        "step_2_r_trigger": 1.5,         # +1.5R profit triggers step 2
        "step_2_r_lock": 1.00,           # lock at +1.00R
        "tp_r": 2.2,                     # +2.2R full Take-Profit
        "state_file": "bot_state_ladder.json"
    },
    "trailing": {
        "id": "trailing",
        "name": "Balanced Trailing Scalper",
        "badge": "⚡ TRAILING",
        "description": "Dynamic Trailing: +0.25% Fee Shield, 0.28% High-Watermark Trailing @ +0.50%, +2.2R TP",
        "starting_capital": 100.0,
        "allocated_margin": 25.0,
        "leverage": 5,
        "max_positions": 3,
        "daily_target": 3.0,
        "daily_max_loss": 3.0,
        "early_be_trigger_pct": 0.0025, # +0.25% profit triggers early BE
        "fee_shield_offset": 0.0010,     # +0.10% lock
        "trailing_trigger_pct": 0.0050,  # +0.50% profit triggers trailing ratchet
        "trailing_dist_pct": 0.0028,     # 0.28% trail distance behind peak
        "tp_r": 2.2,
        "state_file": "bot_state_trailing.json"
    },
    "runner": {
        "id": "runner",
        "name": "Swing Runner (Baseline)",
        "badge": "🎯 RUNNER",
        "description": "High-Conviction Swing Runner: +1.0R Break-Even, Wide +2.2R Take-Profit Target",
        "starting_capital": 100.0,
        "allocated_margin": 25.0,
        "leverage": 5,
        "max_positions": 3,
        "daily_target": 3.0,
        "daily_max_loss": 3.0,
        "be_trigger_r": 1.0,             # +1.0R profit triggers BE
        "be_fee_offset": 0.0018,         # +0.18% lock
        "tp_r": 2.2,
        "state_file": "bot_state_runner.json"
    }
}

# Web Server
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8088

