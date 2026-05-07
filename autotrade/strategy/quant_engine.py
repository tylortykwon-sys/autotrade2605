"""
퀀트 스탁 옵티마이저 — 44전략 그리드 서치 + 샤프 지수 최적화
전략 카테고리: RSI(8) | BB(6) | SMA/EMA Cross(8) | MACD(5) | Stochastic(4) |
               Volume(5) | ATR Breakout(4) | Combo(4) = 44전략
"""
import json
import logging
from itertools import product

import numpy as np
import pandas as pd

from data.database import get_connection, get_ohlcv
from strategy.indicators import (
    add_all_indicators, calc_atr, calc_bollinger_bands, calc_ema,
    calc_macd, calc_rsi, calc_sma, calc_stochastic,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# 44전략 정의
# ──────────────────────────────────────────────────────────────
STRATEGIES: dict[str, dict] = {
    # ── RSI 계열 (8) ──────────────────────────────────────────
    "RSI_MeanReversion": {
        "params": {"period": [7, 10, 14, 21], "oversold": [20, 25, 30], "overbought": [70, 75, 80]},
        "signal_fn": "rsi_mean_reversion",
    },
    "RSI_Trend": {
        "params": {"period": [7, 14, 21], "mid": [45, 50, 55]},
        "signal_fn": "rsi_trend",
    },
    "RSI_Divergence": {
        "params": {"period": [14, 21], "smooth": [3, 5]},
        "signal_fn": "rsi_divergence",
    },
    "RSI_BB_Combo": {
        "params": {"rsi_period": [14], "bb_period": [20], "oversold": [30, 35]},
        "signal_fn": "rsi_bb_combo",
    },
    "RSI_Cross50": {
        "params": {"period": [7, 10, 14]},
        "signal_fn": "rsi_cross50",
    },
    "RSI_OB_OS": {
        "params": {"period": [9, 14], "oversold": [25, 30], "overbought": [70, 75]},
        "signal_fn": "rsi_ob_os",
    },
    "RSI_SlopeUp": {
        "params": {"period": [14, 21], "slope_days": [3, 5]},
        "signal_fn": "rsi_slope_up",
    },
    "RSI_DoubleDip": {
        "params": {"period": [14], "oversold": [30, 35], "lookback": [5, 7]},
        "signal_fn": "rsi_double_dip",
    },

    # ── 볼린저 밴드 계열 (6) ──────────────────────────────────
    "BB_MeanReversion": {
        "params": {"period": [15, 20, 25], "std": [1.5, 2.0, 2.5]},
        "signal_fn": "bb_mean_reversion",
    },
    "BB_Breakout": {
        "params": {"period": [20, 25], "std": [2.0, 2.5]},
        "signal_fn": "bb_breakout",
    },
    "BB_Squeeze": {
        "params": {"period": [20], "std": [2.0], "squeeze_pct": [0.03, 0.05]},
        "signal_fn": "bb_squeeze",
    },
    "BB_Walk": {
        "params": {"period": [20], "std": [2.0, 2.5], "days": [2, 3]},
        "signal_fn": "bb_walk",
    },
    "BB_Width_Trend": {
        "params": {"period": [20], "std": [2.0], "expand_pct": [0.1, 0.2]},
        "signal_fn": "bb_width_trend",
    },
    "BB_Pct_B": {
        "params": {"period": [20], "std": [2.0], "buy_pct": [0.1, 0.2], "sell_pct": [0.8, 0.9]},
        "signal_fn": "bb_pct_b",
    },

    # ── SMA / EMA 크로스 계열 (8) ─────────────────────────────
    "SMA_Cross_Short": {
        "params": {"fast": [5, 10], "slow": [20, 30]},
        "signal_fn": "sma_cross",
    },
    "SMA_Cross_Mid": {
        "params": {"fast": [20, 30], "slow": [60, 100]},
        "signal_fn": "sma_cross",
    },
    "SMA_Cross_Long": {
        "params": {"fast": [60], "slow": [120, 200]},
        "signal_fn": "sma_cross",
    },
    "EMA_Cross_Fast": {
        "params": {"fast": [5, 9], "slow": [21, 26]},
        "signal_fn": "ema_cross",
    },
    "EMA_Cross_Mid": {
        "params": {"fast": [12, 20], "slow": [50, 60]},
        "signal_fn": "ema_cross",
    },
    "Triple_SMA": {
        "params": {"fast": [5, 10], "mid": [20, 30], "slow": [60]},
        "signal_fn": "triple_sma",
    },
    "Price_SMA_Touch": {
        "params": {"period": [20, 60], "tolerance": [0.01, 0.02]},
        "signal_fn": "price_sma_touch",
    },
    "SMA_Slope": {
        "params": {"period": [20, 60], "slope_days": [3, 5]},
        "signal_fn": "sma_slope",
    },

    # ── MACD 계열 (5) ─────────────────────────────────────────
    "MACD_Cross": {
        "params": {"fast": [9, 12], "slow": [21, 26], "signal": [7, 9]},
        "signal_fn": "macd_cross",
    },
    "MACD_Zero": {
        "params": {"fast": [12], "slow": [26], "signal": [9]},
        "signal_fn": "macd_zero",
    },
    "MACD_Histogram": {
        "params": {"fast": [12], "slow": [26], "signal": [9], "hist_min": [0]},
        "signal_fn": "macd_histogram",
    },
    "MACD_Divergence": {
        "params": {"fast": [12], "slow": [26], "signal": [9], "lookback": [5, 7]},
        "signal_fn": "macd_divergence",
    },
    "MACD_RSI_Combo": {
        "params": {"fast": [12], "slow": [26], "signal": [9], "rsi_period": [14], "oversold": [40]},
        "signal_fn": "macd_rsi_combo",
    },

    # ── 스토캐스틱 계열 (4) ───────────────────────────────────
    "Stoch_Cross": {
        "params": {"k": [9, 14], "d": [3, 5], "oversold": [20, 25], "overbought": [75, 80]},
        "signal_fn": "stoch_cross",
    },
    "Stoch_OB_OS": {
        "params": {"k": [14], "d": [3], "oversold": [20], "overbought": [80]},
        "signal_fn": "stoch_ob_os",
    },
    "Stoch_RSI_Combo": {
        "params": {"k": [14], "d": [3], "rsi_period": [14], "oversold": [30]},
        "signal_fn": "stoch_rsi_combo",
    },
    "Stoch_SlowK": {
        "params": {"k": [14, 21], "d": [3], "slow_k": [3]},
        "signal_fn": "stoch_slow_k",
    },

    # ── 거래량 계열 (5) ───────────────────────────────────────
    "Volume_Breakout": {
        "params": {"vol_period": [5, 10], "vol_mult": [1.5, 2.0], "price_pct": [0.01, 0.02]},
        "signal_fn": "volume_breakout",
    },
    "OBV_Trend": {
        "params": {"obv_period": [10, 20]},
        "signal_fn": "obv_trend",
    },
    "Volume_Spike": {
        "params": {"vol_period": [5], "spike_mult": [2.0, 3.0]},
        "signal_fn": "volume_spike",
    },
    "Price_Volume_Confirm": {
        "params": {"price_pct": [0.01, 0.02], "vol_mult": [1.5, 2.0]},
        "signal_fn": "price_volume_confirm",
    },
    "Volume_Dry_Up": {
        "params": {"vol_period": [5, 10], "dry_ratio": [0.5, 0.6]},
        "signal_fn": "volume_dry_up",
    },

    # ── ATR 돌파 계열 (4) ─────────────────────────────────────
    "ATR_Breakout": {
        "params": {"atr_period": [14], "mult": [0.5, 1.0]},
        "signal_fn": "atr_breakout",
    },
    "ATR_Channel": {
        "params": {"atr_period": [14], "sma_period": [20], "mult": [1.5, 2.0]},
        "signal_fn": "atr_channel",
    },
    "Volatility_Contraction": {
        "params": {"atr_period": [14], "lookback": [10, 20], "contract_pct": [0.7, 0.8]},
        "signal_fn": "volatility_contraction",
    },
    "Range_Breakout": {
        "params": {"period": [5, 10], "pct": [0.01, 0.02]},
        "signal_fn": "range_breakout",
    },

    # ── 복합 계열 (4) ─────────────────────────────────────────
    "Trend_Pullback": {
        "params": {"sma_period": [60], "rsi_period": [14], "rsi_buy": [40, 45]},
        "signal_fn": "trend_pullback",
    },
    "Momentum_Reversal": {
        "params": {"rsi_period": [14], "bb_period": [20], "vol_mult": [1.5]},
        "signal_fn": "momentum_reversal",
    },
    "Golden_Cross_Volume": {
        "params": {"fast": [20], "slow": [60], "vol_mult": [1.3, 1.5]},
        "signal_fn": "golden_cross_volume",
    },
    "Multi_Confirm": {
        "params": {"rsi_period": [14], "bb_period": [20], "macd_fast": [12], "macd_slow": [26]},
        "signal_fn": "multi_confirm",
    },
}


# ──────────────────────────────────────────────────────────────
# 시그널 함수
# ──────────────────────────────────────────────────────────────

def rsi_mean_reversion(df, period=14, oversold=30, overbought=70):
    rsi = calc_rsi(df["close"], period)
    s = pd.Series(0, index=df.index)
    s[rsi < oversold] = 1
    s[rsi > overbought] = -1
    return s

def rsi_trend(df, period=14, mid=50):
    rsi = calc_rsi(df["close"], period)
    s = pd.Series(0, index=df.index)
    s[(rsi > mid) & (rsi.shift() <= mid)] = 1
    s[(rsi < mid) & (rsi.shift() >= mid)] = -1
    return s

def rsi_divergence(df, period=14, smooth=3):
    rsi = calc_rsi(df["close"], period).rolling(smooth).mean()
    s = pd.Series(0, index=df.index)
    price_low = df["close"].rolling(5).min() == df["close"]
    rsi_rising = rsi > rsi.shift(3)
    s[price_low & rsi_rising] = 1
    return s

def rsi_bb_combo(df, rsi_period=14, bb_period=20, oversold=30):
    rsi = calc_rsi(df["close"], rsi_period)
    _, _, lower = calc_bollinger_bands(df["close"], bb_period)
    s = pd.Series(0, index=df.index)
    s[(rsi < oversold) & (df["close"] <= lower)] = 1
    s[rsi > 70] = -1
    return s

def rsi_cross50(df, period=14):
    rsi = calc_rsi(df["close"], period)
    s = pd.Series(0, index=df.index)
    s[(rsi > 50) & (rsi.shift() <= 50)] = 1
    s[(rsi < 50) & (rsi.shift() >= 50)] = -1
    return s

def rsi_ob_os(df, period=14, oversold=30, overbought=70):
    return rsi_mean_reversion(df, period, oversold, overbought)

def rsi_slope_up(df, period=14, slope_days=3):
    rsi = calc_rsi(df["close"], period)
    slope = rsi - rsi.shift(slope_days)
    s = pd.Series(0, index=df.index)
    s[(rsi < 40) & (slope > 0)] = 1
    s[rsi > 70] = -1
    return s

def rsi_double_dip(df, period=14, oversold=30, lookback=5):
    rsi = calc_rsi(df["close"], period)
    prev_low = rsi.shift(1).rolling(lookback).min()
    s = pd.Series(0, index=df.index)
    s[(rsi < oversold) & (prev_low < oversold)] = 1
    s[rsi > 70] = -1
    return s

def bb_mean_reversion(df, period=20, std=2.0):
    upper, _, lower = calc_bollinger_bands(df["close"], period, std)
    s = pd.Series(0, index=df.index)
    s[df["close"] <= lower] = 1
    s[df["close"] >= upper] = -1
    return s

def bb_breakout(df, period=20, std=2.0):
    upper, _, lower = calc_bollinger_bands(df["close"], period, std)
    s = pd.Series(0, index=df.index)
    s[(df["close"] > upper) & (df["close"].shift() <= upper.shift())] = 1
    s[(df["close"] < lower) & (df["close"].shift() >= lower.shift())] = -1
    return s

def bb_squeeze(df, period=20, std=2.0, squeeze_pct=0.05):
    upper, mid, lower = calc_bollinger_bands(df["close"], period, std)
    width = (upper - lower) / mid
    squeezed = width < squeeze_pct
    s = pd.Series(0, index=df.index)
    s[squeezed & (df["close"] > mid)] = 1
    s[squeezed & (df["close"] < mid)] = -1
    return s

def bb_walk(df, period=20, std=2.0, days=2):
    upper, _, lower = calc_bollinger_bands(df["close"], period, std)
    near_upper = (df["close"] >= upper * 0.99).rolling(days).sum() >= days
    s = pd.Series(0, index=df.index)
    s[near_upper] = 1
    s[df["close"] <= lower] = -1
    return s

def bb_width_trend(df, period=20, std=2.0, expand_pct=0.1):
    upper, mid, lower = calc_bollinger_bands(df["close"], period, std)
    width = (upper - lower) / mid
    expanding = width > width.shift(3) * (1 + expand_pct)
    s = pd.Series(0, index=df.index)
    s[expanding & (df["close"] > mid)] = 1
    s[expanding & (df["close"] < mid)] = -1
    return s

def bb_pct_b(df, period=20, std=2.0, buy_pct=0.1, sell_pct=0.9):
    upper, _, lower = calc_bollinger_bands(df["close"], period, std)
    pct_b = (df["close"] - lower) / (upper - lower + 1e-9)
    s = pd.Series(0, index=df.index)
    s[pct_b <= buy_pct] = 1
    s[pct_b >= sell_pct] = -1
    return s

def sma_cross(df, fast=20, slow=60):
    sma_f = calc_sma(df["close"], fast)
    sma_s = calc_sma(df["close"], slow)
    s = pd.Series(0, index=df.index)
    s[(sma_f > sma_s) & (sma_f.shift() <= sma_s.shift())] = 1
    s[(sma_f < sma_s) & (sma_f.shift() >= sma_s.shift())] = -1
    return s

def ema_cross(df, fast=12, slow=26):
    ema_f = calc_ema(df["close"], fast)
    ema_s = calc_ema(df["close"], slow)
    s = pd.Series(0, index=df.index)
    s[(ema_f > ema_s) & (ema_f.shift() <= ema_s.shift())] = 1
    s[(ema_f < ema_s) & (ema_f.shift() >= ema_s.shift())] = -1
    return s

def triple_sma(df, fast=5, mid=20, slow=60):
    sf = calc_sma(df["close"], fast)
    sm = calc_sma(df["close"], mid)
    ss = calc_sma(df["close"], slow)
    s = pd.Series(0, index=df.index)
    s[(sf > sm) & (sm > ss) & ~((sf.shift() > sm.shift()) & (sm.shift() > ss.shift()))] = 1
    s[(sf < sm) & (sm < ss)] = -1
    return s

def price_sma_touch(df, period=20, tolerance=0.01):
    sma = calc_sma(df["close"], period)
    near = (df["close"] - sma).abs() / sma <= tolerance
    above = df["close"] > sma
    s = pd.Series(0, index=df.index)
    s[near & above] = 1
    s[near & ~above] = -1
    return s

def sma_slope(df, period=20, slope_days=3):
    sma = calc_sma(df["close"], period)
    slope = sma - sma.shift(slope_days)
    s = pd.Series(0, index=df.index)
    s[(slope > 0) & (slope.shift() <= 0)] = 1
    s[(slope < 0) & (slope.shift() >= 0)] = -1
    return s

def macd_cross(df, fast=12, slow=26, signal=9):
    macd, sig_line, _ = calc_macd(df["close"], fast, slow, signal)
    s = pd.Series(0, index=df.index)
    s[(macd > sig_line) & (macd.shift() <= sig_line.shift())] = 1
    s[(macd < sig_line) & (macd.shift() >= sig_line.shift())] = -1
    return s

def macd_zero(df, fast=12, slow=26, signal=9):
    macd, _, _ = calc_macd(df["close"], fast, slow, signal)
    s = pd.Series(0, index=df.index)
    s[(macd > 0) & (macd.shift() <= 0)] = 1
    s[(macd < 0) & (macd.shift() >= 0)] = -1
    return s

def macd_histogram(df, fast=12, slow=26, signal=9, hist_min=0):
    _, _, hist = calc_macd(df["close"], fast, slow, signal)
    s = pd.Series(0, index=df.index)
    s[(hist > hist_min) & (hist.shift() <= hist_min)] = 1
    s[(hist < 0) & (hist.shift() >= 0)] = -1
    return s

def macd_divergence(df, fast=12, slow=26, signal=9, lookback=5):
    macd, _, _ = calc_macd(df["close"], fast, slow, signal)
    price_low = df["close"].rolling(lookback).min() == df["close"]
    macd_rising = macd > macd.shift(3)
    s = pd.Series(0, index=df.index)
    s[price_low & macd_rising] = 1
    s[macd < macd.shift(lookback)] = -1
    return s

def macd_rsi_combo(df, fast=12, slow=26, signal=9, rsi_period=14, oversold=40):
    macd, sig_line, _ = calc_macd(df["close"], fast, slow, signal)
    rsi = calc_rsi(df["close"], rsi_period)
    s = pd.Series(0, index=df.index)
    s[(macd > sig_line) & (rsi < oversold)] = 1
    s[(macd < sig_line) & (rsi > 70)] = -1
    return s

def stoch_cross(df, k=14, d=3, oversold=20, overbought=80):
    stoch_k, stoch_d = calc_stochastic(df["high"], df["low"], df["close"], k, d)
    s = pd.Series(0, index=df.index)
    buy = (stoch_k > stoch_d) & (stoch_k.shift() <= stoch_d.shift()) & (stoch_k < oversold + 20)
    sell = (stoch_k < stoch_d) & (stoch_k.shift() >= stoch_d.shift()) & (stoch_k > overbought - 20)
    s[buy] = 1
    s[sell] = -1
    return s

def stoch_ob_os(df, k=14, d=3, oversold=20, overbought=80):
    stoch_k, _ = calc_stochastic(df["high"], df["low"], df["close"], k, d)
    s = pd.Series(0, index=df.index)
    s[stoch_k < oversold] = 1
    s[stoch_k > overbought] = -1
    return s

def stoch_rsi_combo(df, k=14, d=3, rsi_period=14, oversold=30):
    stoch_k, _ = calc_stochastic(df["high"], df["low"], df["close"], k, d)
    rsi = calc_rsi(df["close"], rsi_period)
    s = pd.Series(0, index=df.index)
    s[(stoch_k < 30) & (rsi < oversold)] = 1
    s[(stoch_k > 70) & (rsi > 70)] = -1
    return s

def stoch_slow_k(df, k=14, d=3, slow_k=3):
    stoch_k, stoch_d = calc_stochastic(df["high"], df["low"], df["close"], k, d)
    slow = stoch_k.rolling(slow_k).mean()
    s = pd.Series(0, index=df.index)
    s[(slow > stoch_d) & (slow.shift() <= stoch_d.shift())] = 1
    s[(slow < stoch_d) & (slow.shift() >= stoch_d.shift())] = -1
    return s

def volume_breakout(df, vol_period=5, vol_mult=1.5, price_pct=0.01):
    avg_vol = df["volume"].rolling(vol_period).mean()
    price_up = df["close"].pct_change() >= price_pct
    vol_surge = df["volume"] >= avg_vol * vol_mult
    s = pd.Series(0, index=df.index)
    s[price_up & vol_surge] = 1
    s[~price_up & vol_surge] = -1
    return s

def obv_trend(df, obv_period=10):
    from strategy.indicators import calc_obv
    obv = calc_obv(df["close"], df["volume"])
    obv_sma = obv.rolling(obv_period).mean()
    s = pd.Series(0, index=df.index)
    s[(obv > obv_sma) & (obv.shift() <= obv_sma.shift())] = 1
    s[(obv < obv_sma) & (obv.shift() >= obv_sma.shift())] = -1
    return s

def volume_spike(df, vol_period=5, spike_mult=2.0):
    avg_vol = df["volume"].rolling(vol_period).mean()
    spike = df["volume"] >= avg_vol * spike_mult
    s = pd.Series(0, index=df.index)
    s[spike & (df["close"] > df["close"].shift())] = 1
    return s

def price_volume_confirm(df, price_pct=0.01, vol_mult=1.5):
    avg_vol = df["volume"].rolling(5).mean()
    s = pd.Series(0, index=df.index)
    s[(df["close"].pct_change() >= price_pct) & (df["volume"] >= avg_vol * vol_mult)] = 1
    s[(df["close"].pct_change() <= -price_pct) & (df["volume"] >= avg_vol * vol_mult)] = -1
    return s

def volume_dry_up(df, vol_period=5, dry_ratio=0.5):
    avg_vol = df["volume"].rolling(vol_period).mean()
    dry = df["volume"] <= avg_vol * dry_ratio
    s = pd.Series(0, index=df.index)
    s[dry & (df["close"] > calc_sma(df["close"], 20))] = 1
    return s

def atr_breakout(df, atr_period=14, mult=1.0):
    atr = calc_atr(df["high"], df["low"], df["close"], atr_period)
    upper = df["close"].shift() + atr * mult
    s = pd.Series(0, index=df.index)
    s[df["close"] > upper] = 1
    s[df["close"] < df["close"].shift() - atr * mult] = -1
    return s

def atr_channel(df, atr_period=14, sma_period=20, mult=2.0):
    atr = calc_atr(df["high"], df["low"], df["close"], atr_period)
    sma = calc_sma(df["close"], sma_period)
    s = pd.Series(0, index=df.index)
    s[df["close"] > sma + atr * mult] = 1
    s[df["close"] < sma - atr * mult] = -1
    return s

def volatility_contraction(df, atr_period=14, lookback=20, contract_pct=0.7):
    atr = calc_atr(df["high"], df["low"], df["close"], atr_period)
    contracted = atr <= atr.rolling(lookback).max() * contract_pct
    s = pd.Series(0, index=df.index)
    s[contracted & (df["close"] > calc_sma(df["close"], 20))] = 1
    return s

def range_breakout(df, period=5, pct=0.01):
    high = df["high"].rolling(period).max()
    low = df["low"].rolling(period).min()
    s = pd.Series(0, index=df.index)
    s[df["close"] > high.shift() * (1 + pct)] = 1
    s[df["close"] < low.shift() * (1 - pct)] = -1
    return s

def trend_pullback(df, sma_period=60, rsi_period=14, rsi_buy=45):
    sma = calc_sma(df["close"], sma_period)
    rsi = calc_rsi(df["close"], rsi_period)
    s = pd.Series(0, index=df.index)
    s[(df["close"] > sma) & (rsi < rsi_buy)] = 1
    s[rsi > 70] = -1
    return s

def momentum_reversal(df, rsi_period=14, bb_period=20, vol_mult=1.5):
    rsi = calc_rsi(df["close"], rsi_period)
    _, _, lower = calc_bollinger_bands(df["close"], bb_period)
    avg_vol = df["volume"].rolling(5).mean()
    s = pd.Series(0, index=df.index)
    s[(rsi < 35) & (df["close"] <= lower) & (df["volume"] >= avg_vol * vol_mult)] = 1
    s[rsi > 70] = -1
    return s

def golden_cross_volume(df, fast=20, slow=60, vol_mult=1.3):
    sma_f = calc_sma(df["close"], fast)
    sma_s = calc_sma(df["close"], slow)
    avg_vol = df["volume"].rolling(5).mean()
    cross = (sma_f > sma_s) & (sma_f.shift() <= sma_s.shift())
    s = pd.Series(0, index=df.index)
    s[cross & (df["volume"] >= avg_vol * vol_mult)] = 1
    s[(sma_f < sma_s) & (sma_f.shift() >= sma_s.shift())] = -1
    return s

def multi_confirm(df, rsi_period=14, bb_period=20, macd_fast=12, macd_slow=26):
    rsi = calc_rsi(df["close"], rsi_period)
    _, _, lower = calc_bollinger_bands(df["close"], bb_period)
    macd, sig, _ = calc_macd(df["close"], macd_fast, macd_slow)
    s = pd.Series(0, index=df.index)
    s[(rsi < 40) & (df["close"] <= lower * 1.01) & (macd > sig)] = 1
    s[(rsi > 70) | (df["close"] >= calc_bollinger_bands(df["close"], bb_period)[0] * 0.99)] = -1
    return s


# ──────────────────────────────────────────────────────────────
# 백테스트 엔진
# ──────────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, signal: pd.Series, initial: float = 10_000_000) -> dict:
    position, cash, buy_price = 0, initial, 0.0
    portfolio = initial
    trades, wins = 0, 0
    peak = initial
    max_drawdown = 0.0

    for i in range(1, len(df)):
        sig = signal.iloc[i]
        price = float(df["close"].iloc[i])

        if sig == 1 and position == 0 and price > 0:
            position = int(cash // price)
            cash -= position * price
            buy_price = price

        elif sig == -1 and position > 0:
            cash += position * price
            trades += 1
            if price > buy_price:
                wins += 1
            position = 0

        portfolio = cash + position * price
        peak = max(peak, portfolio)
        dd = (portfolio - peak) / peak
        max_drawdown = min(max_drawdown, dd)

    # 미청산 포지션 강제 정산
    if position > 0:
        final_price = float(df["close"].iloc[-1])
        cash += position * final_price
        trades += 1
        if final_price > buy_price:
            wins += 1
        portfolio = cash

    total_return = (portfolio - initial) / initial
    win_rate = wins / trades if trades > 0 else 0.0

    close_arr = df["close"].values.astype(float)
    daily_ret = (close_arr[1:] - close_arr[:-1]) / (close_arr[:-1] + 1e-9)
    daily_ret = daily_ret[np.isfinite(daily_ret)]
    sharpe = (daily_ret.mean() / daily_ret.std() * (252 ** 0.5)
              if len(daily_ret) > 1 and daily_ret.std() > 0 else 0.0)

    return {
        "total_return": round(total_return, 4),
        "mdd": round(max_drawdown, 4),
        "win_rate": round(win_rate, 4),
        "trades": trades,
        "sharpe": round(sharpe, 4),
    }


def grid_search(ticker: str, strategy_name: str) -> dict | None:
    """단일 종목 × 단일 전략 그리드 서치"""
    rows = get_ohlcv(ticker, days=365 * 3)
    if len(rows) < 200:
        logger.debug(f"[GS] {ticker} 데이터 부족 ({len(rows)}건)")
        return None

    df = pd.DataFrame(rows)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])

    strategy = STRATEGIES.get(strategy_name)
    if not strategy:
        return None

    fn = globals().get(strategy["signal_fn"])
    if fn is None:
        return None

    best: dict = {"sharpe": -999.0}
    param_grid = strategy["params"]
    keys = list(param_grid.keys())

    for combo in product(*param_grid.values()):
        params = dict(zip(keys, combo))
        try:
            sig = fn(df, **params)
            result = backtest(df, sig)
        except Exception:
            continue

        if (result["sharpe"] > best["sharpe"]
                and result["mdd"] > -0.20
                and result["win_rate"] >= 0.45
                and result["trades"] >= 5):
            best = {**result, "params": params, "strategy": strategy_name, "ticker": ticker}

    return best if "params" in best else None


def run_full_optimization(tickers: list[str]):
    """전 종목 × 전 전략 최적화 (월 1회 야간 배치)"""
    conn = get_connection()
    saved = 0
    total = len(tickers) * len(STRATEGIES)
    done = 0

    for ticker in tickers:
        for strategy_name in STRATEGIES:
            result = grid_search(ticker, strategy_name)
            done += 1
            if result and result.get("sharpe", 0) >= 1.0:
                conn.execute(
                    '''INSERT OR REPLACE INTO strategy_params
                       (ticker, strategy, params, sharpe, mdd, win_rate)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (ticker, strategy_name,
                     json.dumps(result["params"]),
                     result["sharpe"], result["mdd"], result["win_rate"]),
                )
                saved += 1
            if done % 50 == 0:
                logger.info(f"[Optimizer] {done}/{total} 완료, 저장: {saved}건")

    conn.commit()
    conn.close()
    logger.info(f"[Optimizer] 최적화 완료 — {saved}개 전략-종목 조합 저장")
    return saved
