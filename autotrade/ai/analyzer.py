"""
거래 분석기 — Phase 7에서 Haiku 연동 완성 예정
현재: 규칙 기반 텍스트 분석만 수행
"""
import logging
from datetime import datetime

from data.database import get_trades

logger = logging.getLogger(__name__)


def analyze_today_trades() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    trades = [t for t in get_trades(limit=50)
              if t.get("executed_at", "").startswith(today)]
    sells = [t for t in trades if t["side"] == "SELL"]

    if not sells:
        return "오늘 체결된 매도 거래 없음"

    total_pnl = sum(t.get("pnl", 0) or 0 for t in sells)
    wins = sum(1 for t in sells if (t.get("pnl") or 0) > 0)

    return (
        f"오늘 매도 {len(sells)}건 / 총 손익 {total_pnl:+,.0f}원 / "
        f"승률 {wins/len(sells)*100:.0f}% (Phase 7에서 Haiku 분석 연동 예정)"
    )
