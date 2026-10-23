"""
VELOCITY SCALPER: Configuration & Quantitative Parameters
Tailored for $100 Account Aggressive Micro-Scalping (Target: $1.00 - $3.00+ / day per engine)
Total Portfolio Capital: $300 across 3 Parallel Quantitative Engines.
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
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]
DEFAULT_TIMEFRAME = "1h"  # 1-hour verified structural breakout engine (4-6 high-yield trades/day)
SCAN_INTERVAL_SECONDS = 3 # 3-second live scan cycle

# --- CAPITAL & POSITION SIZING ---
STARTING_CAPITAL_USDT = float(os.getenv("STARTING_CAPITAL_USDT", "100.0"))
LEVERAGE = int(os.getenv("LEVERAGE", "10"))                  # 10x isolated leverage
ALLOCATED_MARGIN_USDT = float(os.getenv("ALLOCATED_MARGIN_USDT", "30.0")) # $30 margin per trade ($300 notional)
MAX_OPEN_POSITIONS = 3 # Max 3 concurrent positions per engine

# --- STRICT DAILY CIRCUIT BREAKERS ---
DAILY_PROFIT_TARGET_USDT = float(os.getenv("DAILY_PROFIT_TARGET_USDT", "3.00")) # User Target: $1.00 - $3.00 / day
DAILY_MAX_LOSS_USDT = float(os.getenv("DAILY_MAX_LOSS_USDT", "6.00"))           # Stop trading if -$6.00 daily loss hits
MAX_CONSECUTIVE_LOSSES = 2
COOLDOWN_MINUTES = 30

# --- QUANTITATIVE PARAMETERS (DONCHIAN TURTLE-SURFER 20/200) ---
PARAMS = {
    "donchian_period": 20,   # 20-Hour High/Low Structural Channel
    "ema_trend": 200,        # 200 EMA Macro Regime Filter
    "atr_period": 14,
    "sl_atr_mult": 1.8,      # Stop Loss distance = 1.8 * ATR
    "rr_ratio": 2.6,         # Take Profit = 2.6 * Risk (+$7.80 gain on win!)
    "be_trigger_r": 1.2,     # Move SL to Break-Even once profit reaches +1.2R (+$3.60)
    "be_fee_offset": 0.0018, # +0.18% to guarantee net profit after all exchange fees
    "risk_per_trade_usd": 3.00, # Fixed $3.00 risk per trade (3% of $100 account)
    "fee_rate": 0.0004,      # 0.04% taker fee per leg (0.08% roundtrip)
    "rsi_period": 14,
}

# --- TRI-ENGINE SPECIALIZED CONFIGURATIONS ---
ENGINE_CONFIGS = {
    "runner": {
        "id": "runner",
        "name": "Donchian Swing Runner",
        "badge": "🎯 RUNNER",
        "description": "20h Donchian Breakout + 200 EMA, +1.2R BE Shield, Wide +2.6R TP (Target: +$7.80/win)",
        "starting_capital": 100.0,
        "allocated_margin": 30.0,
        "leverage": 10,
        "max_positions": 3,
        "daily_target": 3.0,
        "daily_max_loss": 6.0,
        "be_trigger_r": 1.2,             # +1.2R profit triggers Break-Even
        "be_fee_offset": 0.0018,         # +0.18% fee shield lock
        "tp_r": 2.6,                     # +2.6R full Take-Profit
        "state_file": "bot_state_runner.json"
    },
    "ladder": {
        "id": "ladder",
        "name": "Tactical Step Ladder",
        "badge": "🛡️ LADDER",
        "description": "2-Stage Tactical Step Lock: +1.0R Step 1 (+0.50R Lock), +1.8R Step 2 (+1.20R Lock), +2.6R TP",
        "starting_capital": 100.0,
        "allocated_margin": 30.0,
        "leverage": 10,
        "max_positions": 3,
        "daily_target": 3.0,
        "daily_max_loss": 6.0,
        "fee_shield_offset": 0.0018,
        "step_1_r_trigger": 1.0,         # +1.0R profit triggers step 1 lock
        "step_1_r_lock": 0.50,           # lock at +0.50R (guaranteed win!)
        "step_2_r_trigger": 1.8,         # +1.8R profit triggers step 2 lock
        "step_2_r_lock": 1.20,           # lock at +1.20R
        "tp_r": 2.6,                     # +2.6R full Take-Profit
        "state_file": "bot_state_ladder.json"
    },
    "trailing": {
        "id": "trailing",
        "name": "Dynamic Volatility Surfer",
        "badge": "⚡ TRAILING",
        "description": "Dynamic Volatility Trailing: +1.2R BE Shield, +1.6R Trailing (0.60 sl_dist Behind Peak)",
        "starting_capital": 100.0,
        "allocated_margin": 30.0,
        "leverage": 10,
        "max_positions": 3,
        "daily_target": 3.0,
        "daily_max_loss": 6.0,
        "be_trigger_r": 1.2,
        "fee_shield_offset": 0.0018,
        "trailing_trigger_r": 1.6,       # +1.6R profit activates dynamic trailing ratchet
        "trailing_dist_r": 0.60,         # Trails 0.60 * sl_dist behind highest peak
        "tp_r": 2.8,                     # +2.8R wide runner
        "state_file": "bot_state_trailing.json"
    }
}

# Web Server
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8088
