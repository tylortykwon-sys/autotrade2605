import pandas as pd
import numpy as np


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calc_bollinger_bands(close: pd.Series, period: int = 20, std: float = 2.0):
    """returns (upper, mid, lower)"""
    mid = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    return mid + std * sigma, mid, mid - std * sigma


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """returns (macd, signal_line, histogram)"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line, macd - signal_line


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical = (high + low + close) / 3
    return (typical * volume).cumsum() / volume.cumsum()


def calc_sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period).mean()


def calc_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def calc_stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                    k_period: int = 14, d_period: int = 3):
    """returns (%K, %D)"""
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    k = (close - lowest) / (highest - lowest + 1e-9) * 100
    d = k.rolling(d_period).mean()
    return k, d


def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume"""
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    df["rsi_14"] = calc_rsi(c, 14)
    df["rsi_21"] = calc_rsi(c, 21)

    df["bb_upper"], df["bb_mid"], df["bb_lower"] = calc_bollinger_bands(c, 20, 2.0)
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

    df["macd"], df["macd_signal"], df["macd_hist"] = calc_macd(c)

    df["atr_14"] = calc_atr(h, l, c, 14)
    df["atr_pct"] = df["atr_14"] / c * 100

    df["sma_5"]  = calc_sma(c, 5)
    df["sma_20"] = calc_sma(c, 20)
    df["sma_60"] = calc_sma(c, 60)
    df["sma_120"] = calc_sma(c, 120)

    df["ema_9"]  = calc_ema(c, 9)
    df["ema_21"] = calc_ema(c, 21)

    df["vwap"] = calc_vwap(h, l, c, v)

    df["stoch_k"], df["stoch_d"] = calc_stochastic(h, l, c)

    df["obv"] = calc_obv(c, v)
    df["vol_ratio"] = v / v.rolling(5).mean()

    return df
