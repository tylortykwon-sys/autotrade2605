"""
일일 보고서 생성기

구성:
  1. DB 거래 통계 (손익, 승률, 전략별)
  2. Haiku AI 코멘트 (analyze_today_trades)
  3. 내일 감시 종목 (suggest_tomorrow_watchlist)
"""
import logging
from datetime import datetime

from data.database import get_trades

logger = logging.getLogger(__name__)


def build_daily_report() -> str:
    today  = datetime.now().strftime("%Y-%m-%d")
    trades = get_trades(limit=200)
    today_trades = [t for t in trades if (t.get("executed_at") or "").startswith(today)]

    buys  = [t for t in today_trades if t["side"] == "BUY"]
    sells = [t for t in today_trades if t["side"] == "SELL"]

    total_pnl = sum(t.get("pnl", 0) or 0 for t in sells)
    wins      = sum(1 for t in sells if (t.get("pnl") or 0) > 0)
    win_rate  = wins / len(sells) * 100 if sells else 0

    # 전략별 손익
    by_strategy: dict[str, dict] = {}
    for t in sells:
        s = t.get("strategy") or "기타"
        if s not in by_strategy:
            by_strategy[s] = {"pnl": 0, "count": 0, "wins": 0}
        by_strategy[s]["pnl"]   += t.get("pnl", 0) or 0
        by_strategy[s]["count"] += 1
        by_strategy[s]["wins"]  += 1 if (t.get("pnl") or 0) > 0 else 0

    lines = [
        f"[일일 보고] {today}",
        "━" * 26,
        f"매매: {len(today_trades)}건  (매수 {len(buys)} / 매도 {len(sells)})",
        f"손익: {total_pnl:+,.0f}원",
        f"승률: {win_rate:.0f}%  ({wins}승 {len(sells)-wins}패)",
    ]

    if by_strategy:
        lines.append("전략별:")
        for s, v in by_strategy.items():
            wr = v["wins"] / v["count"] * 100 if v["count"] else 0
            lines.append(f"  {s}: {v['pnl']:+,.0f}원  ({wr:.0f}%  {v['count']}건)")

    lines.append("━" * 26)

    # AI 코멘트
    try:
        from ai.analyzer import analyze_today_trades
        ai_comment = analyze_today_trades()
        lines.append(f"AI: {ai_comment}")
    except Exception as e:
        logger.warning(f"[Report] AI 코멘트 실패: {e}")
        lines.append("AI: (분석 불가)")

    # 내일 감시 종목
    try:
        from ai.analyzer import suggest_tomorrow_watchlist
        watchlist = suggest_tomorrow_watchlist(top_n=3)
        if watchlist:
            lines.append(f"내일 감시: {' '.join(watchlist)}")
    except Exception as e:
        logger.debug(f"[Report] 감시 종목 추천 실패: {e}")

    return "\n".join(lines)


def build_trade_alert(ticker: str, side: str, price: float,
                      quantity: int, pnl: float = 0,
                      pnl_pct: float = 0, strategy: str = "",
                      reason: str = "") -> str:
    """매수/매도 체결 즉시 알림 텍스트"""
    if side == "BUY":
        return (
            f"<b>매수 체결</b>\n"
            f"종목: {ticker}  수량: {quantity}주\n"
            f"단가: {price:,.0f}원\n"
            f"전략: {strategy}"
        )
    else:
        sign  = "+" if pnl >= 0 else ""
        label = reason or "매도"
        return (
            f"<b>매도 체결</b> [{label}]\n"
            f"종목: {ticker}  수량: {quantity}주\n"
            f"단가: {price:,.0f}원\n"
            f"손익: {sign}{pnl:,.0f}원  ({sign}{pnl_pct:.2f}%)"
        )
