"""
VELOCITY SCALPER: Strategy Module
Quantitative Momentum-Pullback Engine with 200-EMA Regime Filter and Dynamic ATR Risk Bounds.
"""
import numpy as np
import pandas as pd
from config import PARAMS

class VelocityStrategy:
    def __init__(self, params=PARAMS):
        self.params = params

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enrich OHLCV DataFrame with quantitative series."""
        df = df.copy()
        c = df["close"]
        h = df["high"]
        l = df["low"]
        o = df["open"]
        
        # 1. EMAs
        df["ema_fast"] = c.ewm(span=self.params["ema_fast"], adjust=False).mean()
        df["ema_slow"] = c.ewm(span=self.params["ema_slow"], adjust=False).mean()
        df["ema_trend"] = c.ewm(span=self.params["ema_trend"], adjust=False).mean()
        
        # 2. True Range & ATR
        prev_close = c.shift(1)
        tr = np.maximum(h - l, np.maximum(abs(h - prev_close), abs(l - prev_close)))
        df["atr"] = tr.rolling(self.params["atr_period"]).mean()
        
        # 3. Macro Regime Detection (200 EMA Rule)
        df["regime"] = 0
        df.loc[c > df["ema_trend"], "regime"] = 1   # Bullish Regime
        df.loc[c < df["ema_trend"], "regime"] = -1  # Bearish Regime
        
        # 4. Pullback & Crossover Signals
        fast = df["ema_fast"]
        slow = df["ema_slow"]
        buy_cross = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        sell_cross = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        
        df["signal"] = 0
        df.loc[(df["regime"] == 1) & buy_cross, "signal"] = 1    # Long Signal
        df.loc[(df["regime"] == -1) & sell_cross, "signal"] = -1 # Short Signal
        
        return df

    def analyze_latest(self, df: pd.DataFrame) -> dict:
        """Evaluate the latest closed bar and ticking candle for live dashboard and bot loop."""
        if len(df) < self.params["ema_trend"] + 5:
            return {"status": "WARMING_UP", "signal": 0, "signal_label": "WARMING_UP"}

        df_ind = self.prepare_indicators(df)
        curr = df_ind.iloc[-1]
        prev = df_ind.iloc[-2]
        
        close = curr["close"]
        ema_trend = curr["ema_trend"]
        ema_fast = curr["ema_fast"]
        ema_slow = curr["ema_slow"]
        atr = curr["atr"]
        regime = "BULLISH" if curr["regime"] == 1 else ("BEARISH" if curr["regime"] == -1 else "NEUTRAL")
        
        # Use previous closed bar's confirmed signal or current ticking crossover
        sig = curr["signal"]
        if sig == 0 and prev["signal"] != 0:
            sig = prev["signal"]

        signal_label = "BUY" if sig == 1 else ("SELL" if sig == -1 else "HOLD")
        
        # Dynamic Risk Distances
        sl_dist = self.params["sl_atr_mult"] * atr if pd.notna(atr) and atr > 0 else (close * 0.005)
        tp_dist = self.params["rr_ratio"] * sl_dist

        if sig == 1:
            target_sl = round(close - sl_dist, 4)
            target_tp = round(close + tp_dist, 4)
            be_price = round(close + sl_dist, 4)
        elif sig == -1:
            target_sl = round(close + sl_dist, 4)
            target_tp = round(close - tp_dist, 4)
            be_price = round(close - sl_dist, 4)
        else:
            target_sl = 0.0
            target_tp = 0.0
            be_price = 0.0

        ema_diff_pct = ((ema_fast - ema_slow) / ema_slow) * 100
        trend_distance_pct = ((close - ema_trend) / ema_trend) * 100

        return {
            "time": str(df_ind.index[-1]),
            "price": float(close),
            "regime": regime,
            "signal": int(sig),
            "signal_label": signal_label,
            "ema_fast": float(round(ema_fast, 4)),
            "ema_slow": float(round(ema_slow, 4)),
            "ema_trend": float(round(ema_trend, 4)),
            "ema_diff_pct": float(round(ema_diff_pct, 3)),
            "trend_distance_pct": float(round(trend_distance_pct, 2)),
            "atr": float(round(atr, 4)) if pd.notna(atr) else 0.0,
            "sl_dist": float(round(sl_dist, 4)),
            "tp_dist": float(round(tp_dist, 4)),
            "target_sl": target_sl,
            "target_tp": target_tp,
            "be_trigger_price": be_price
        }
