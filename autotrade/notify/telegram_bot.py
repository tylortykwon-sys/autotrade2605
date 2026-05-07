"""
텔레그램 알림 발송 모듈

기능:
  - HTML 파싱 메시지 발송 (볼드, 코드 등)
  - 재시도 로직 (최대 3회, 지수 백오프)
  - 토큰 미설정 시 로그만 출력 (에러 없이 작동)
  - 메시지 타입별 헬퍼 함수
"""
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_MAX_RETRY = 3
_BASE_WAIT = 2  # 초


def _get_credentials() -> tuple[str, str]:
    return os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """텔레그램 메시지 발송. 토큰 미설정 시 로그만 출력."""
    token, chat_id = _get_credentials()

    if not token or not chat_id:
        logger.info(f"[Telegram-stub] {text[:200]}")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}

    for attempt in range(1, _MAX_RETRY + 1):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            # 429 Too Many Requests → 대기 후 재시도
            if resp.status_code == 429:
                retry_after = int(resp.json().get("parameters", {}).get("retry_after", _BASE_WAIT * attempt))
                logger.warning(f"[Telegram] Rate limit — {retry_after}s 대기 (시도 {attempt})")
                time.sleep(retry_after)
                continue
            logger.error(f"[Telegram] HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        except requests.exceptions.Timeout:
            wait = _BASE_WAIT ** attempt
            logger.warning(f"[Telegram] 타임아웃 — {wait}s 대기 (시도 {attempt}/{_MAX_RETRY})")
            if attempt < _MAX_RETRY:
                time.sleep(wait)
        except Exception as e:
            logger.error(f"[Telegram] 예외: {e}")
            return False

    logger.error(f"[Telegram] {_MAX_RETRY}회 재시도 후 실패")
    return False


# ── 메시지 타입별 헬퍼 ──────────────────────────────────────────────

def send_buy_alert(ticker: str, quantity: int, price: float,
                   strategy: str, amount: float) -> bool:
    text = (
        f"<b>📈 매수 체결</b>\n"
        f"종목: <code>{ticker}</code>  수량: {quantity}주\n"
        f"단가: {price:,.0f}원\n"
        f"전략: {strategy}\n"
        f"투자: {amount:,.0f}원"
    )
    return send_message(text)


def send_sell_alert(ticker: str, quantity: int, price: float,
                    pnl: float, pnl_pct: float, reason: str = "") -> bool:
    sign = "+" if pnl >= 0 else ""
    icon = "✅" if pnl >= 0 else "🔴"
    label = reason or "매도"
    text = (
        f"<b>{icon} 매도 체결</b> [{label}]\n"
        f"종목: <code>{ticker}</code>  수량: {quantity}주\n"
        f"단가: {price:,.0f}원\n"
        f"손익: <b>{sign}{pnl:,.0f}원</b>  ({sign}{pnl_pct:.2f}%)"
    )
    return send_message(text)


def send_daily_report(report_text: str) -> bool:
    header = "<b>📊 일일 보고서</b>\n"
    return send_message(header + report_text)


def send_system_alert(msg: str, level: str = "INFO") -> bool:
    icons = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "🚨"}
    icon = icons.get(level, "ℹ️")
    return send_message(f"{icon} <b>[시스템]</b> {msg}")


def send_circuit_breaker_alert(reason: str) -> bool:
    text = (
        f"🛑 <b>서킷 브레이커 발동</b>\n"
        f"사유: {reason}\n"
        f"당일 신규 매수 중단"
    )
    return send_message(text)


def send_sentiment_alert(score: float, label: str, reason: str) -> bool:
    icon = "🟢" if score > 0.2 else ("🔴" if score < -0.2 else "🟡")
    text = (
        f"{icon} <b>시장 감성 분석</b>\n"
        f"점수: {score:+.2f}  ({label})\n"
        f"근거: {reason}"
    )
    return send_message(text)
