"""
일일 보고서 생성기
Phase 8에서 AI 코멘트 연동 완성 예정 / 현재는 DB 기반 텍스트 보고서
"""
import logging
from datetime import datetime

from data.database import get_trades

logger = logging.getLogger(__name__)


def build_daily_report() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    trades = get_trades(limit=100)
    today_trades = [t for t in trades if t.get("executed_at", "").startswith(today)]

    buys  = [t for t in today_trades if t["side"] == "BUY"]
    sells = [t for t in today_trades if t["side"] == "SELL"]

    total_pnl   = sum(t.get("pnl", 0) or 0 for t in sells)
    wins        = sum(1 for t in sells if (t.get("pnl") or 0) > 0)
    win_rate    = wins / len(sells) * 100 if sells else 0

    lines = [
        f"[일일 보고] {today}",
        "━" * 24,
        f"매매: {len(today_trades)}건 (매수 {len(buys)} / 매도 {len(sells)})",
        f"손익: {total_pnl:+,.0f}원",
        f"승률: {win_rate:.0f}% ({wins}승 {len(sells)-wins}패)",
        "━" * 24,
    ]

    if sells:
        lines.append("상세:")
        for t in sells:
            pnl = t.get("pnl") or 0
            pct = t.get("pnl_pct") or 0
            lines.append(f"  {t['ticker']} {pnl:+,.0f}원 ({pct:+.2f}%) [{t.get('strategy','')}]")

    lines.append("(AI 코멘트: Phase 8 연동 후 추가)")
    return "\n".join(lines)
