"""
VELOCITY SCALPER: Strategy Module
Quantitative Donchian Turtle-Surfer (20/200 Breakout Engine).
Engineered for High-Yield Aggressive Micro-Scalping ($1.00 - $3.00+ / day on $100 capital).
"""
import numpy as np
import pandas as pd
from config import PARAMS

class VelocityStrategy:
    def __init__(self, params=PARAMS):
        self.params = params

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enrich OHLCV DataFrame with Donchian channel and quantitative series."""
        df = df.copy()
        c = df["close"]
        h = df["high"]
        l = df["low"]
        o = df["open"]
        v = df["volume"]
        
        # 1. Donchian 20-Hour Channel Bounds (shifted by 1 to use completed previous 20 bars)
        period = self.params.get("donchian_period", 20)
        df["high_ch"] = h.rolling(period).max().shift(1)
        df["low_ch"] = l.rolling(period).min().shift(1)
        
        # 2. 200 EMA Macro Regime Shield
        ema_trend_p = self.params.get("ema_trend", 200)
        df["ema_trend"] = c.ewm(span=ema_trend_p, adjust=False).mean()
        df["ema_fast"] = c.ewm(span=9, adjust=False).mean()
        df["ema_slow"] = c.ewm(span=21, adjust=False).mean()
        
        # 3. True Range & Average True Range (ATR 14)
        prev_close = c.shift(1)
        tr = np.maximum(h - l, np.maximum(abs(h - prev_close), abs(l - prev_close)))
        df["atr"] = tr.rolling(self.params.get("atr_period", 14)).mean()
        
        # 4. Relative Strength Index (RSI 14)
        delta = c.diff()
        gain = (delta.where(delta > 0, 0.0)).rolling(self.params.get("rsi_period", 14)).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(self.params.get("rsi_period", 14)).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))
        
        # 5. Macro Regime Detection
        df["regime"] = 0
        df.loc[c > df["ema_trend"], "regime"] = 1   # Bullish Regime (Only Longs allowed)
        df.loc[c < df["ema_trend"], "regime"] = -1  # Bearish Regime (Only Shorts allowed)
        
        # 6. Breakout Signals
        # Bullish: Price breaks 20-period High while in Bullish Regime (> 200 EMA)
        # Bearish: Price breaks 20-period Low while in Bearish Regime (< 200 EMA)
        df["signal"] = 0
        df.loc[(df["regime"] == 1) & (h > df["high_ch"]), "signal"] = 1
        df.loc[(df["regime"] == -1) & (l < df["low_ch"]), "signal"] = -1
        
        return df

    def analyze_latest(self, df: pd.DataFrame) -> dict:
        """Evaluate latest market data and generate high-yield trade parameters."""
        if len(df) < self.params.get("ema_trend", 200) + 5:
            return {"status": "WARMING_UP", "signal": 0, "signal_label": "WARMING_UP"}

        df_ind = self.prepare_indicators(df)
        curr = df_ind.iloc[-1]   # current active/ticking candle
        prev = df_ind.iloc[-2]   # confirmed closed hourly candle
        
        close = float(curr["close"])
        high = float(curr["high"])
        low = float(curr["low"])
        high_ch = float(curr["high_ch"]) if pd.notna(curr["high_ch"]) else close * 1.01
        low_ch = float(curr["low_ch"]) if pd.notna(curr["low_ch"]) else close * 0.99
        ema_trend = float(curr["ema_trend"])
        ema_fast = float(curr["ema_fast"])
        ema_slow = float(curr["ema_slow"])
        atr = float(curr["atr"]) if pd.notna(curr["atr"]) else (close * 0.008)
        
        regime = "BULLISH" if close > ema_trend else "BEARISH"
        
        # Detect breakout event
        sig = 0
        if close > ema_trend and high > high_ch:
            sig = 1
        elif close < ema_trend and low < low_ch:
            sig = -1
            
        signal_label = "BUY" if sig == 1 else ("SELL" if sig == -1 else "HOLD")
        
        # Dynamic Risk Distances: SL = 1.8 ATR, TP = 2.6R (+ $7.80 target), BE = +1.2R
        sl_mult = self.params.get("sl_atr_mult", 1.8)
        rr_ratio = self.params.get("rr_ratio", 2.6)
        be_mult = self.params.get("be_trigger_r", 1.2)
        
        sl_dist = sl_mult * atr if atr > 0 else (close * 0.008)
        tp_dist = rr_ratio * sl_dist
        be_dist = be_mult * sl_dist

        if sig == 1:
            target_sl = round(close - sl_dist, 4)
            target_tp = round(close + tp_dist, 4)
            be_price = round(close + be_dist, 4)
        elif sig == -1:
            target_sl = round(close + sl_dist, 4)
            target_tp = round(close - tp_dist, 4)
            be_price = round(close - be_dist, 4)
        else:
            target_sl = 0.0
            target_tp = 0.0
            be_price = 0.0

        ema_diff_pct = ((ema_fast - ema_slow) / ema_slow) * 100 if ema_slow > 0 else 0.0
        trend_distance_pct = ((close - ema_trend) / ema_trend) * 100 if ema_trend > 0 else 0.0

        return {
            "time": str(df_ind.index[-1]),
            "price": float(close),
            "regime": regime,
            "signal": int(sig),
            "signal_label": signal_label,
            "high_ch": float(round(high_ch, 4)),
            "low_ch": float(round(low_ch, 4)),
            "ema_fast": float(round(ema_fast, 4)),
            "ema_slow": float(round(ema_slow, 4)),
            "ema_trend": float(round(ema_trend, 4)),
            "ema_diff_pct": float(round(ema_diff_pct, 3)),
            "trend_distance_pct": float(round(trend_distance_pct, 2)),
            "rsi": float(round(curr["rsi"], 2)) if pd.notna(curr.get("rsi")) else 50.0,
            "atr": float(round(atr, 4)),
            "sl_dist": float(round(sl_dist, 4)),
            "tp_dist": float(round(tp_dist, 4)),
            "target_sl": target_sl,
            "target_tp": target_tp,
            "be_trigger_price": be_price
        }
