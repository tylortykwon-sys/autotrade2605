"""
Circuit Breaker — 다층 손실 방어 시스템

레벨 1: 개별 종목 손절 (-2%)        → order_manager가 처리
레벨 2: 일일 손실 한도 (-3%)         → 이 클래스
레벨 3: 연속 손실 감지 (3일 연속)    → 이 클래스 + DB 조회
"""
import logging
import os
from datetime import datetime, timedelta

from notify.telegram_bot import send_message

logger = logging.getLogger(__name__)

DAILY_LOSS_LIMIT      = float(os.getenv("DAILY_LOSS_LIMIT", "-0.03"))
CONSECUTIVE_LOSS_DAYS = int(os.getenv("CONSECUTIVE_LOSS_DAYS", "3"))


class CircuitBreaker:
    def __init__(self):
        self._triggered   = False
        self._start_value: float | None = None
        self._current_loss_pct: float   = 0.0

    # ── 초기화 ────────────────────────────────────────────────

    def reset(self):
        """매일 장 개시 시 호출"""
        self._triggered        = False
        self._start_value      = None
        self._current_loss_pct = 0.0
        logger.info("[CB] Circuit Breaker 초기화")

    def set_start(self, value: float):
        self._start_value = value
        logger.info(f"[CB] 기준 자산: {value:,.0f}원")

    # ── 실시간 감시 ───────────────────────────────────────────

    def check(self, kis_client) -> bool:
        """잔고 조회로 일일 손실률 실시간 감시. 발동 시 True 반환."""
        if self._triggered:
            return True
        if self._start_value is None:
            return False

        try:
            current = kis_client.get_cash()
            self._current_loss_pct = (current - self._start_value) / self._start_value

            if self._current_loss_pct <= DAILY_LOSS_LIMIT:
                self._trigger(self._current_loss_pct)
                return True

            # 경고 구간: 한도의 80% 도달 시 알림
            warn_threshold = DAILY_LOSS_LIMIT * 0.8
            if self._current_loss_pct <= warn_threshold:
                logger.warning(
                    f"[CB] 손실 경고: {self._current_loss_pct*100:.2f}% "
                    f"(한도 {DAILY_LOSS_LIMIT*100:.0f}%의 80%)"
                )
        except Exception as e:
            logger.error(f"[CB] 잔고 조회 실패: {e}")

        return False

    def check_from_db(self) -> bool:
        """DB 거래 기록 기반으로 당일 실현 손익 확인 (API 불필요)"""
        if self._triggered:
            return True

        try:
            from data.database import get_connection
            conn   = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COALESCE(SUM(pnl), 0) as daily_pnl
                FROM trades
                WHERE date(executed_at) = date('now', 'localtime')
                  AND side = 'SELL'
            """)
            daily_pnl = cursor.fetchone()[0] or 0.0
            conn.close()

            if self._start_value and self._start_value > 0:
                loss_pct = daily_pnl / self._start_value
                if loss_pct <= DAILY_LOSS_LIMIT:
                    self._trigger(loss_pct)
                    return True
        except Exception as e:
            logger.error(f"[CB] DB 손익 조회 실패: {e}")

        return False

    # ── 연속 손실 감지 ────────────────────────────────────────

    def check_consecutive_losses(self) -> int:
        """최근 N일 연속 손실 일수 반환"""
        try:
            from data.database import get_connection
            conn   = get_connection()
            cursor = conn.cursor()
            consecutive = 0
            for i in range(1, CONSECUTIVE_LOSS_DAYS + 2):
                check_date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                cursor.execute("""
                    SELECT COALESCE(SUM(pnl), 0)
                    FROM trades
                    WHERE date(executed_at) = ?
                      AND side = 'SELL'
                """, (check_date,))
                pnl = cursor.fetchone()[0] or 0.0
                if pnl < 0:
                    consecutive += 1
                else:
                    break
            conn.close()
            if consecutive >= CONSECUTIVE_LOSS_DAYS:
                logger.warning(f"[CB] {consecutive}일 연속 손실 감지 — 포지션 축소 권장")
                send_message(
                    f"주의: {consecutive}일 연속 손실\n"
                    f"MAX_SLOTS를 절반으로 줄이는 것을 권장합니다"
                )
            return consecutive
        except Exception as e:
            logger.error(f"[CB] 연속 손실 확인 실패: {e}")
            return 0

    # ── 상태 조회 ─────────────────────────────────────────────

    def is_triggered(self) -> bool:
        return self._triggered

    def current_loss_pct(self) -> float:
        return self._current_loss_pct

    def status(self) -> dict:
        return {
            "triggered":       self._triggered,
            "start_value":     self._start_value,
            "current_loss_pct": round(self._current_loss_pct * 100, 2),
            "limit_pct":       DAILY_LOSS_LIMIT * 100,
        }

    # ── 내부 ─────────────────────────────────────────────────

    def _trigger(self, loss_pct: float):
        self._triggered = True
        msg = (
            f"Circuit Breaker 발동!\n"
            f"일일 손실: {loss_pct*100:.2f}% (한도: {DAILY_LOSS_LIMIT*100:.0f}%)\n"
            f"당일 신규 매수 중단 — 기존 포지션 즉시 청산 권장"
        )
        send_message(msg)
        logger.warning(f"[CB] {msg}")
