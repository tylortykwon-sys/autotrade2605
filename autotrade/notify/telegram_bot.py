"""
텔레그램 알림 발송 (Phase 8에서 완성 예정)
현재: 설정 미완료 시 로그로만 출력
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)


def send_message(text: str) -> bool:
    """텔레그램 메시지 발송. 토큰 미설정 시 로그만 출력."""
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.info(f"[Telegram-stub] {text}")
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"[Telegram] 발송 실패: {e}")
        return False
