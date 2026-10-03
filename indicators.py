"""
VELOCITY SCALPER: Quantitative Indicators Module
Vectorized calculation for 1m / 3m high-frequency candlestick charts.
Includes: EMA Trend, Bollinger Bands, Stochastic RSI, ATR, and Volume surge.
"""
import numpy as np
import pandas as pd

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Vectorized Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()

def calculate_bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0):
    """Bollinger Bands: Middle, Upper, Lower, and BandWidth %."""
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    bandwidth = (upper - lower) / middle * 100
    return middle, upper, lower, bandwidth

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Standard Relative Strength Index."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_stoch_rsi(series: pd.Series, rsi_period: int = 14, stoch_period: int = 14, k_period: int = 3, d_period: int = 3):
    """
    Stochastic RSI (%K and %D).
    Crucial for timing sniper entries at extreme turning points.
    """
    rsi = calculate_rsi(series, rsi_period)
    min_rsi = rsi.rolling(window=stoch_period).min()
    max_rsi = rsi.rolling(window=stoch_period).max()
    stoch = ((rsi - min_rsi) / (max_rsi - min_rsi + 1e-9)) * 100
    k = stoch.rolling(window=k_period).mean()
    d = k.rolling(window=d_period).mean()
    return k, d, rsi

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range for dynamic volatility stop calculation."""
    h = df["high"]
    l = df["low"]
    c_prev = df["close"].shift(1)
    tr = np.maximum(h - l, np.maximum(abs(h - c_prev), abs(l - c_prev)))
    return tr.rolling(window=period).mean()

def compute_all_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Enrich 1m candle DataFrame with all required quantitative series."""
    df = df.copy()
    c = df["close"]
    
    # 1. EMAs
    df["ema_fast"] = calculate_ema(c, params.get("ema_fast", 20))
    df["ema_slow"] = calculate_ema(c, params.get("ema_slow", 50))
    
    # 2. Bollinger Bands
    bb_p = params.get("bb_period", 20)
    bb_s = params.get("bb_std", 2.0)
    df["bb_mid"], df["bb_upper"], df["bb_lower"], df["bb_width"] = calculate_bollinger_bands(c, bb_p, bb_s)
    
    # 3. Stochastic RSI
    df["stoch_k"], df["stoch_d"], df["rsi"] = calculate_stoch_rsi(
        c,
        rsi_period=params.get("rsi_period", 14),
        stoch_period=params.get("stoch_period", 14),
        k_period=params.get("stoch_k", 3),
        d_period=params.get("stoch_d", 3)
    )
    
    # 4. ATR
    df["atr"] = calculate_atr(df, period=14)
    
    # 5. Volume Moving Average & Surge
    vol_p = params.get("volume_ma_period", 20)
    df["vol_ma"] = df["volume"].rolling(window=vol_p).mean()
    df["vol_ratio"] = df["volume"] / (df["vol_ma"] + 1e-9)
    
    return df
