"""
전략 피드백 루프 — 실거래 성과 기반 자기 학습

주기: 주 1회 (월요일 08:00)
동작:
  1. 최근 N일 실거래 성과 집계 (전략별 win_rate, avg_pnl_pct, Sharpe)
  2. DB 저장 벤치마크(기대 win_rate)와 비교
  3. 이탈 전략 목록 반환 (재최적화 / 일시정지 대상)
  4. Haiku로 요약 코멘트 생성 (API 가용 시)
"""
import logging
from datetime import datetime, timedelta

from data.database import get_connection

logger = logging.getLogger(__name__)

# 이탈 판정 임계값
_UNDERPERFORM_WIN_RATE  = 0.40   # 승률 < 40% → 재최적화 대상
_CRITICAL_WIN_RATE      = 0.30   # 승률 < 30% (거래 ≥ 10) → 일시정지 후보
_MIN_TRADES_FOR_EVAL    = 5      # 평가 최소 거래 수


def analyze_recent_performance(days: int = 7) -> dict:
    """
    최근 N일 실거래 성과 전략별 집계.

    반환:
      stats         : {strategy_name: {trades, wins, win_rate, avg_pnl_pct, total_pnl}}
      underperformers: win_rate < 0.40 이고 거래 >= 5인 전략 목록
      critical      : win_rate < 0.30 이고 거래 >= 10인 전략 목록 (일시정지 후보)
      period_days   : 분석 기간
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strategy,
               COUNT(*) as trades,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
               ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
               ROUND(SUM(pnl), 0) as total_pnl
        FROM trades
        WHERE side = 'SELL'
          AND date(executed_at) >= date(?)
        GROUP BY strategy
    """, (since,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    stats: dict[str, dict] = {}
    for r in rows:
        name = r["strategy"] or "기타"
        count = r["trades"] or 0
        wins  = r["wins"]  or 0
        stats[name] = {
            "trades":      count,
            "wins":        wins,
            "win_rate":    round(wins / count, 4) if count > 0 else 0.0,
            "avg_pnl_pct": r["avg_pnl_pct"] or 0.0,
            "total_pnl":   r["total_pnl"]   or 0.0,
        }

    underperformers = [
        name for name, v in stats.items()
        if v["trades"] >= _MIN_TRADES_FOR_EVAL and v["win_rate"] < _UNDERPERFORM_WIN_RATE
    ]
    critical = [
        name for name, v in stats.items()
        if v["trades"] >= 10 and v["win_rate"] < _CRITICAL_WIN_RATE
    ]

    logger.info(
        f"[Feedback] {days}일 분석 완료 — 전략 {len(stats)}개 | "
        f"이탈 {len(underperformers)}개 | 위험 {len(critical)}개"
    )
    return {
        "stats":           stats,
        "underperformers": underperformers,
        "critical":        critical,
        "period_days":     days,
        "since":           since,
    }


def _compare_vs_benchmark(stats: dict[str, dict]) -> list[dict]:
    """DB 벤치마크 win_rate과 비교해 gap이 큰 전략 반환."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strategy, ROUND(AVG(win_rate), 4) as bench_wr
        FROM strategy_params
        GROUP BY strategy
    """)
    benchmarks = {r["strategy"]: r["bench_wr"] for r in cursor.fetchall()}
    conn.close()

    gaps = []
    for name, v in stats.items():
        if v["trades"] < _MIN_TRADES_FOR_EVAL:
            continue
        bench = benchmarks.get(name)
        if bench and bench > 0:
            gap = bench - v["win_rate"]   # 양수 = 기대치보다 낮음
            if gap > 0.10:               # 10%p 이상 이탈
                gaps.append({
                    "strategy":    name,
                    "actual_wr":   v["win_rate"],
                    "bench_wr":    bench,
                    "gap":         round(gap, 4),
                    "trades":      v["trades"],
                })
    gaps.sort(key=lambda x: x["gap"], reverse=True)
    return gaps


def generate_feedback_report(days: int = 7) -> str:
    """
    주간 피드백 보고서 생성.
    DB 통계 + 벤치마크 비교 + Haiku 코멘트 (가능 시).
    """
    result = analyze_recent_performance(days)
    stats  = result["stats"]
    gaps   = _compare_vs_benchmark(stats)

    lines = [
        f"[주간 피드백] 최근 {days}일 전략 성과",
        "━" * 30,
    ]

    if not stats:
        lines.append("거래 데이터 없음")
    else:
        for name, v in sorted(stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
            flag = " ⚠️" if name in result["underperformers"] else ""
            flag += " 🚨" if name in result["critical"] else ""
            lines.append(
                f"{name}{flag}: "
                f"승률 {v['win_rate']*100:.0f}%  "
                f"({v['trades']}건  {v['total_pnl']:+,.0f}원)"
            )

    if gaps:
        lines.append("")
        lines.append("▼ 벤치마크 이탈 전략")
        for g in gaps[:5]:
            lines.append(
                f"  {g['strategy']}: 실제 {g['actual_wr']*100:.0f}% "
                f"vs 기대 {g['bench_wr']*100:.0f}% "
                f"(↓{g['gap']*100:.1f}%p)"
            )

    lines.append("━" * 30)

    # Haiku 코멘트
    try:
        from ai.haiku_client import HaikuClient
        haiku = HaikuClient()
        if haiku._ready and stats:
            import json as _json
            prompt = f"""최근 {days}일 자동매매 전략별 성과:
{_json.dumps(stats, ensure_ascii=False, indent=2)}

벤치마크 이탈 전략:
{_json.dumps(gaps[:3], ensure_ascii=False, indent=2)}

성과가 나쁜 전략의 주요 원인 1가지와 파라미터 조정 방향을 한 줄로 말해주세요."""
            comment = haiku.analyze(prompt, max_tokens=200)
            lines.append(f"AI 조언: {comment}")
    except Exception as e:
        logger.debug(f"[Feedback] Haiku 코멘트 실패: {e}")

    return "\n".join(lines)


def get_recently_traded_tickers(days: int = 7) -> list[str]:
    """최근 N일 내 매도가 발생한 종목 목록 반환."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT ticker FROM trades
        WHERE side = 'SELL' AND date(executed_at) >= date(?)
    """, (since,))
    tickers = [r["ticker"] for r in cursor.fetchall()]
    conn.close()
    return tickers
