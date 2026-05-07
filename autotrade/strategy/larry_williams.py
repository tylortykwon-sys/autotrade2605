import logging

import pandas as pd

from strategy.indicators import calc_atr

logger = logging.getLogger(__name__)


def calc_trigger_price(open_price: float, high_14min: float, low_14min: float,
                       k: float = 0.5) -> float:
    """장 개시 후 14분 레인지 × K → 매수 트리거가"""
    return open_price + (high_14min - low_14min) * k


def calc_position_size(total_capital: float, atr_pct: float) -> float:
    """ATR% 기반 동적 포지션 사이징"""
    if atr_pct >= 3.0:
        ratio = 0.05
    elif atr_pct >= 1.5:
        ratio = 0.10
    elif atr_pct >= 0.5:
        ratio = 0.20
    else:
        ratio = 0.0
    return total_capital * ratio


def check_breakout(current_price: float, trigger_price: float,
                   current_volume: int, avg_volume: float,
                   volume_ratio_min: float = 1.3) -> bool:
    """트리거가 돌파 + 거래량 필터"""
    return (current_price >= trigger_price and
            current_volume >= avg_volume * volume_ratio_min)


def get_candidate_tickers(top_n: int = 10) -> list[dict]:
    """변동성 돌파 대상 종목 스크리닝 (ATR 0.5% 이상)"""
    from data.collector import get_top_tickers
    from data.database import get_ohlcv

    tickers = get_top_tickers(top_n=50)
    candidates = []

    for ticker in tickers:
        rows = get_ohlcv(ticker, days=20)
        if len(rows) < 15:
            continue

        df = pd.DataFrame(rows).apply(pd.to_numeric, errors="coerce")
        atr = calc_atr(df["high"], df["low"], df["close"], 14).iloc[-1]
        last_close = df["close"].iloc[-1]
        atr_pct = atr / last_close * 100 if last_close > 0 else 0

        if atr_pct < 0.5:
            continue

        candidates.append({
            "ticker": ticker,
            "last_close": last_close,
            "atr": round(atr, 0),
            "atr_pct": round(atr_pct, 2),
        })

    candidates.sort(key=lambda x: x["atr_pct"])
    return candidates[:top_n]


class LarryWilliamsStrategy:
    """래리 윌리엄스 변동성 돌파 전략 상태 관리자"""

    def __init__(self, total_capital: float, k: float = 0.5):
        self.total_capital = total_capital
        self.k = k
        self.triggers: dict[str, float] = {}
        self.positions: dict[str, dict] = {}

    def set_trigger(self, ticker: str, open_p: float, high_14: float, low_14: float):
        trigger = calc_trigger_price(open_p, high_14, low_14, self.k)
        self.triggers[ticker] = trigger
        logger.info(f"[LW] {ticker} 트리거가: {trigger:,.0f}원 (K={self.k})")

    def should_buy(self, ticker: str, current_price: float,
                   current_volume: int, avg_volume: float) -> bool:
        trigger = self.triggers.get(ticker)
        if trigger is None:
            return False
        return check_breakout(current_price, trigger, current_volume, avg_volume)

    def get_buy_amount(self, atr_pct: float) -> float:
        return calc_position_size(self.total_capital, atr_pct)

    def should_sell(self, ticker: str, current_price: float, buy_price: float,
                    take_profit: float = 0.03, stop_loss: float = -0.02) -> str | None:
        pnl_pct = (current_price - buy_price) / buy_price
        if pnl_pct >= take_profit:
            return "TAKE_PROFIT"
        if pnl_pct <= stop_loss:
            return "STOP_LOSS"
        return None

    def reset_day(self):
        """매일 장 시작 전 트리거/포지션 초기화"""
        self.triggers.clear()
        logger.info("[LW] 일일 리셋 완료")
