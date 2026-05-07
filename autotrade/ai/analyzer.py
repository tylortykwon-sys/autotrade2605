"""
거래 성과 분석기 — Claude Haiku 1일 1회 호출

분석 내용:
  1. 오늘 거래 손익 요약 + 개선점
  2. 전략별 성과 비교
  3. 내일 감시 종목 제안
"""
import json
import logging
from datetime import datetime

from ai.haiku_client import HaikuClient
from data.database import get_connection, get_trades

logger = logging.getLogger(__name__)

_haiku = HaikuClient()

SYSTEM_PROMPT = """\
당신은 국내 주식 자동매매 시스템의 성과 분석 AI입니다.
오늘의 거래 데이터를 보고 간결하게 분석해주세요.
규칙:
- 반드시 한국어로 답변
- 200자 이내로 요약
- 구체적 수치 기반으로 분석
- 감정적 표현 없이 객관적으로
"""


def _get_today_trades() -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticker, side, price, quantity, pnl, pnl_pct, strategy, executed_at
        FROM trades
        WHERE date(executed_at) = date('now', 'localtime')
        ORDER BY executed_at
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def _get_strategy_stats() -> list[dict]:
    """전략별 누적 승률 조회"""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strategy,
               COUNT(*) as total,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
               ROUND(AVG(pnl_pct), 2) as avg_pnl_pct
        FROM trades
        WHERE side = 'SELL'
        GROUP BY strategy
        ORDER BY avg_pnl_pct DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def analyze_today_trades() -> str:
    """오늘 거래 내역 Haiku 분석 (1일 1회)"""
    trades = _get_today_trades()
    sells  = [t for t in trades if t["side"] == "SELL"]

    if not sells:
        return "오늘 체결된 매도 거래 없음"

    total_pnl  = sum(t.get("pnl", 0) or 0 for t in sells)
    wins       = sum(1 for t in sells if (t.get("pnl") or 0) > 0)
    win_rate   = wins / len(sells) * 100 if sells else 0
    strategies = list({t.get("strategy", "") for t in sells})

    prompt = f"""오늘 자동매매 결과:
- 총 거래: {len(sells)}건 (승 {wins}건 / 패 {len(sells)-wins}건)
- 총 손익: {total_pnl:+,.0f}원
- 승률: {win_rate:.0f}%
- 사용 전략: {', '.join(strategies)}
- 거래 상세:
{json.dumps(sells, ensure_ascii=False, default=str, indent=2)}

오늘 성과의 특징 1줄 + 내일 개선점 1가지만 알려주세요."""

    return _haiku.analyze(prompt, system=SYSTEM_PROMPT, max_tokens=300)


def analyze_strategy_performance() -> str:
    """전략별 누적 성과 분석"""
    stats = _get_strategy_stats()
    if not stats:
        return "누적 거래 데이터 없음"

    prompt = f"""전략별 누적 성과:
{json.dumps(stats, ensure_ascii=False, indent=2)}

가장 성과가 좋은 전략과 나쁜 전략을 각각 1개씩 지목하고
파라미터 조정 방향을 한 줄로 제안해주세요."""

    return _haiku.analyze(prompt, system=SYSTEM_PROMPT, max_tokens=200)


def suggest_tomorrow_watchlist(top_n: int = 5) -> list[str]:
    """Haiku 기반 내일 감시 종목 추천 (JSON 응답)"""
    from data.database import get_ohlcv
    from data.collector import get_top_tickers
    from strategy.scoring import score_ticker

    tickers = get_top_tickers(top_n=20)
    scored  = []
    for t in tickers:
        rows = get_ohlcv(t, 10)
        if len(rows) < 5:
            continue
        sc = score_ticker(t)
        scored.append({"ticker": t, "score": sc})

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:10]

    prompt = f"""다음 종목들의 스코어 기반으로 내일 주목할 종목 {top_n}개를 추천하세요.
{json.dumps(top, ensure_ascii=False)}

응답 형식 (JSON 배열만):
["종목코드1", "종목코드2", ...]"""

    result = _haiku.analyze_json(prompt, max_tokens=150)
    if isinstance(result, list):
        return result[:top_n]
    raw = result.get("raw", "")
    # raw가 문자열 배열처럼 보이면 파싱 재시도
    try:
        import re
        codes = re.findall(r'\d{6}', raw)
        return codes[:top_n]
    except Exception:
        return [t["ticker"] for t in top[:top_n]]
