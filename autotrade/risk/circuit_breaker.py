"""
Circuit Breaker — 일일 손실 한도 감시
일일 손실이 DAILY_LOSS_LIMIT(-3%) 초과 시 즉시 전량 청산 + 당일 매매 중단
Phase 6에서 완성 예정 / 현재는 기본 동작 구현
"""
import logging
import os

from notify.telegram_bot import send_message

logger = logging.getLogger(__name__)
DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "-0.03"))


class CircuitBreaker:
    def __init__(self):
        self._triggered = False
        self._start_value: float | None = None

    def reset(self):
        self._triggered = False
        self._start_value = None
        logger.info("[CB] Circuit Breaker 초기화")

    def set_start(self, value: float):
        self._start_value = value
        logger.info(f"[CB] 기준 자산: {value:,.0f}원")

    def check(self, kis_client) -> bool:
        if self._triggered:
            return True
        if self._start_value is None:
            return False
        try:
            current = kis_client.get_cash()
            loss_pct = (current - self._start_value) / self._start_value
            if loss_pct <= DAILY_LOSS_LIMIT:
                self._triggered = True
                msg = (
                    f"Circuit Breaker 발동!\n"
                    f"일일 손실 {loss_pct*100:.2f}% (한도: {DAILY_LOSS_LIMIT*100:.0f}%)\n"
                    f"당일 매매 중단"
                )
                send_message(msg)
                logger.warning(f"[CB] {msg}")
                return True
        except Exception as e:
            logger.error(f"[CB] 잔고 조회 실패: {e}")
        return False

    def is_triggered(self) -> bool:
        return self._triggered
