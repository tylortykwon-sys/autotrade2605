"""
개별 종목 손절/익절 로직

지원 방식:
  1. 고정 비율  : 매수가 대비 -2% / +3%
  2. ATR 트레일링: 최고가 기준 ATR × mult 이하로 하락 시 손절
  3. 시간 손절  : N분 이내 수익 없으면 청산 (오버나잇 방지)
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ── 기본 손절/익절 ─────────────────────────────────────────────

def check_fixed_stop(current_price: float, buy_price: float,
                     stop_pct: float = -0.02,
                     take_pct: float = 0.03) -> str | None:
    """
    고정 비율 손절/익절 확인
    반환: "STOP_LOSS" | "TAKE_PROFIT" | None
    """
    pnl_pct = (current_price - buy_price) / buy_price
    if pnl_pct <= stop_pct:
        return "STOP_LOSS"
    if pnl_pct >= take_pct:
        return "TAKE_PROFIT"
    return None


# ── ATR 트레일링 스탑 ─────────────────────────────────────────

class TrailingStop:
    """최고가 추적 트레일링 스탑"""

    def __init__(self, buy_price: float, atr: float, mult: float = 2.0):
        self.buy_price   = buy_price
        self.atr         = atr
        self.mult        = mult
        self.peak_price  = buy_price          # 진입 후 최고가
        self.stop_price  = buy_price - atr * mult

    def update(self, current_price: float) -> str | None:
        """현재가로 최고가·손절가 갱신. 손절 발동 시 'TRAILING_STOP' 반환."""
        if current_price > self.peak_price:
            self.peak_price = current_price
            self.stop_price = self.peak_price - self.atr * self.mult
            logger.debug(f"[Trailing] 최고가 갱신: {self.peak_price:,.0f} → 손절가: {self.stop_price:,.0f}")

        if current_price <= self.stop_price:
            pnl_pct = (current_price - self.buy_price) / self.buy_price * 100
            logger.info(f"[Trailing] 트레일링 스탑 발동: {current_price:,.0f}원 ({pnl_pct:+.2f}%)")
            return "TRAILING_STOP"
        return None

    def status(self) -> dict:
        return {
            "buy_price":  self.buy_price,
            "peak_price": self.peak_price,
            "stop_price": round(self.stop_price, 0),
            "gap_pct":    round((self.atr * self.mult) / self.peak_price * 100, 2),
        }


# ── 시간 손절 ─────────────────────────────────────────────────

class TimeStop:
    """일정 시간 이후 수익 없으면 강제 청산 (오버나잇 방지)"""

    def __init__(self, buy_price: float,
                 max_hold_minutes: int = 240,
                 min_profit_pct: float = 0.005):
        self.buy_price         = buy_price
        self.entry_time        = datetime.now()
        self.max_hold_minutes  = max_hold_minutes
        self.min_profit_pct    = min_profit_pct

    def check(self, current_price: float) -> str | None:
        """
        보유 시간 초과 & 수익 미달 시 'TIME_STOP' 반환
        수익 중이라면 시간이 지나도 청산하지 않음 (익절 로직에 위임)
        """
        elapsed = (datetime.now() - self.entry_time).total_seconds() / 60
        pnl_pct = (current_price - self.buy_price) / self.buy_price

        if elapsed >= self.max_hold_minutes and pnl_pct < self.min_profit_pct:
            logger.info(
                f"[TimeStop] {elapsed:.0f}분 경과, 수익 {pnl_pct*100:.2f}% → 시간 손절"
            )
            return "TIME_STOP"
        return None


# ── 복합 손절 관리자 ──────────────────────────────────────────

class StopLossManager:
    """
    한 포지션에 대한 손절 조건 통합 관리
    우선순위: 고정 손절 > 트레일링 스탑 > 시간 손절 > 고정 익절
    """

    def __init__(self, buy_price: float, atr: float,
                 stop_pct: float = -0.02, take_pct: float = 0.03,
                 trail_mult: float = 2.0, max_hold_min: int = 240):
        self.buy_price   = buy_price
        self.fixed_stop  = stop_pct
        self.fixed_take  = take_pct
        self.trailing    = TrailingStop(buy_price, atr, trail_mult)
        self.time_stop   = TimeStop(buy_price, max_hold_min)

    def evaluate(self, current_price: float) -> str | None:
        """현재가 기준 손절/익절 조건 평가. 발동 이유 반환."""
        # 1. 고정 손절 (최우선)
        pnl_pct = (current_price - self.buy_price) / self.buy_price
        if pnl_pct <= self.fixed_stop:
            return "STOP_LOSS"

        # 2. 트레일링 스탑
        result = self.trailing.update(current_price)
        if result:
            return result

        # 3. 고정 익절
        if pnl_pct >= self.fixed_take:
            return "TAKE_PROFIT"

        # 4. 시간 손절
        result = self.time_stop.check(current_price)
        if result:
            return result

        return None

    def summary(self, current_price: float) -> dict:
        pnl_pct = (current_price - self.buy_price) / self.buy_price * 100
        return {
            "buy_price":     self.buy_price,
            "current_price": current_price,
            "pnl_pct":       round(pnl_pct, 2),
            "fixed_stop":    round(self.buy_price * (1 + self.fixed_stop), 0),
            "fixed_take":    round(self.buy_price * (1 + self.fixed_take), 0),
            "trailing":      self.trailing.status(),
        }
