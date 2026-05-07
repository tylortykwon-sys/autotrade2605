"""
멀티팩터 스코어링 — 매수 후보 종목 선정 (0~100점)
① 변동성 (30pt): ATR% 0.5~2.5% 이상적 범위
② 수급   (30pt): 거래량 vs 5일 평균 비율
③ 기술적 (40pt): RSI + BB + MACD + SMA 위치
"""
import logging

import pandas as pd

from data.database import get_ohlcv
from strategy.indicators import add_all_indicators

logger = logging.getLogger(__name__)


def score_ticker(ticker: str) -> float:
    rows = get_ohlcv(ticker, days=30)
    if len(rows) < 10:
        return 0.0

    df = pd.DataFrame(rows)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    df = add_all_indicators(df)
    last = df.iloc[-1]
    score = 0.0

    # ① 변동성 (30점)
    atr_pct = last.get("atr_pct", 0)
    if 0.5 <= atr_pct <= 2.5:
        score += 30
    elif atr_pct > 2.5:
        score += 15  # 과고변동 — 절반만

    # ② 수급 (30점) — 거래량 vs 5일 평균
    vol_avg = df["volume"].iloc[-6:-1].mean()
    if vol_avg > 0:
        vol_ratio = df["volume"].iloc[-1] / vol_avg
        if vol_ratio >= 2.0:
            score += 30
        elif vol_ratio >= 1.5:
            score += 20
        elif vol_ratio >= 1.0:
            score += 10

    # ③ 기술적 신호 (40점)
    rsi     = last.get("rsi_14", 50)
    close   = last.get("close", 0)
    bb_low  = last.get("bb_lower", 0)
    sma20   = last.get("sma_20", 0)
    sma60   = last.get("sma_60", 0)
    macd    = last.get("macd", 0)
    macd_s  = last.get("macd_signal", 0)
    stoch_k = last.get("stoch_k", 50)

    if rsi < 35:                      score += 12  # 과매도
    elif rsi < 45:                    score += 6
    if close > 0 and close <= bb_low: score += 10  # BB 하단 터치
    if macd > macd_s:                 score += 8   # MACD 골든크로스
    if sma60 > 0 and close > sma60:   score += 5   # 60일선 위
    if sma20 > 0 and close > sma20:   score += 3   # 20일선 위
    if stoch_k < 25:                  score += 2   # 스토캐스틱 과매도

    return min(score, 100.0)


def get_score_breakdown(ticker: str) -> dict:
    """종목 스코어 상세 분석"""
    rows = get_ohlcv(ticker, days=30)
    if len(rows) < 10:
        return {"ticker": ticker, "score": 0, "reason": "데이터 부족"}

    df = pd.DataFrame(rows)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    df = add_all_indicators(df)
    last = df.iloc[-1]

    atr_pct = last.get("atr_pct", 0)
    vol_avg = df["volume"].iloc[-6:-1].mean()
    vol_ratio = df["volume"].iloc[-1] / vol_avg if vol_avg > 0 else 0
    rsi = last.get("rsi_14", 50)

    return {
        "ticker": ticker,
        "score": round(score_ticker(ticker), 1),
        "close": int(last.get("close", 0)),
        "rsi_14": round(rsi, 1),
        "atr_pct": round(atr_pct, 2),
        "vol_ratio": round(vol_ratio, 2),
        "macd_cross": bool(last.get("macd", 0) > last.get("macd_signal", 0)),
        "above_sma60": bool(last.get("close", 0) > last.get("sma_60", 0)),
    }


def get_buy_candidates(min_score: float = 70.0, top_n: int = 5) -> list[dict]:
    """스코어 기준 매수 후보 종목 반환"""
    from data.collector import get_top_tickers
    tickers = get_top_tickers(top_n=50)

    results = []
    for ticker in tickers:
        try:
            sc = score_ticker(ticker)
            if sc >= min_score:
                results.append({"ticker": ticker, "score": sc})
        except Exception as e:
            logger.debug(f"[Scoring] {ticker} 스코어 실패: {e}")

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"[Scoring] 매수 후보 {len(results)}종목 (min_score={min_score})")
    return results[:top_n]
