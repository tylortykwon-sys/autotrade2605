"""
전략 파라미터 자동 업데이트

동작:
  1. 피드백 루프에서 이탈 전략 목록 수신
  2. 해당 전략 × 최근 거래 종목에 대해 grid_search 재실행
  3. 기존보다 Sharpe 개선 시 DB 업데이트
  4. 극단적 저성과 전략 일시정지 → 쿨다운 후 자동 해제

일시정지 상태:
  파일: learning/.strategy_state.json
  구조: {"PausedStrategyName": {"paused_until": "YYYY-MM-DD", "reason": "...", "fail_count": N}}
"""
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILE = Path(__file__).parent / ".strategy_state.json"
_DEFAULT_PAUSE_DAYS = 14


# ── 상태 파일 I/O ────────────────────────────────────────────────────

def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    _STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


# ── 일시정지 관리 ────────────────────────────────────────────────────

def pause_strategy(name: str, reason: str, pause_days: int = _DEFAULT_PAUSE_DAYS):
    """전략을 pause_days일 동안 일시정지."""
    state = _load_state()
    until = (date.today() + timedelta(days=pause_days)).isoformat()
    prev  = state.get(name, {})
    state[name] = {
        "paused_until": until,
        "reason":       reason,
        "fail_count":   prev.get("fail_count", 0) + 1,
        "paused_at":    date.today().isoformat(),
    }
    _save_state(state)
    logger.warning(f"[Updater] {name} 일시정지: {reason} (until {until}, 누적 {state[name]['fail_count']}회)")


def resume_strategy(name: str):
    """특정 전략 일시정지 해제."""
    state = _load_state()
    if name in state:
        del state[name]
        _save_state(state)
        logger.info(f"[Updater] {name} 일시정지 해제")


def resume_expired_pauses() -> list[str]:
    """만료된 일시정지 자동 해제. 해제된 전략 목록 반환."""
    state  = _load_state()
    today  = date.today().isoformat()
    freed  = [name for name, v in state.items() if v.get("paused_until", "") <= today]
    for name in freed:
        del state[name]
    if freed:
        _save_state(state)
        logger.info(f"[Updater] 일시정지 해제: {freed}")
    return freed


def is_paused(name: str) -> bool:
    state = _load_state()
    if name not in state:
        return False
    until = state[name].get("paused_until", "")
    return until > date.today().isoformat()


def get_paused_strategies() -> list[dict]:
    """현재 활성 일시정지 목록 반환."""
    state = _load_state()
    today = date.today().isoformat()
    return [
        {"strategy": name, **v}
        for name, v in state.items()
        if v.get("paused_until", "") > today
    ]


# ── 파라미터 업데이트 ────────────────────────────────────────────────

def _get_current_sharpe(conn, ticker: str, strategy: str) -> float:
    """DB에 저장된 현재 Sharpe 반환. 없으면 0."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT sharpe FROM strategy_params WHERE ticker=? AND strategy=?",
        (ticker, strategy),
    )
    row = cursor.fetchone()
    return float(row["sharpe"]) if row else 0.0


def run_incremental_optimization(
    tickers: list[str],
    strategies: list[str] | None = None,
) -> dict:
    """
    지정 종목 × 전략 조합에 대해 grid_search 실행 후
    기존보다 Sharpe가 높은 경우에만 DB 업데이트.

    strategies=None → 44개 전체 (이탈 전략 없으면 전체 갱신)
    """
    from data.database import get_connection
    from strategy.quant_engine import STRATEGIES, grid_search

    target_strategies = strategies or list(STRATEGIES.keys())
    active_strategies = [s for s in target_strategies if not is_paused(s)]

    if not active_strategies:
        logger.info("[Updater] 활성 전략 없음 — 최적화 스킵")
        return {"updated": 0, "skipped": 0}

    conn    = get_connection()
    updated = 0
    skipped = 0
    total   = len(tickers) * len(active_strategies)
    done    = 0

    logger.info(f"[Updater] 증분 최적화 시작: {len(tickers)}종목 × {len(active_strategies)}전략 = {total}조합")

    for ticker in tickers:
        for strategy_name in active_strategies:
            done += 1
            try:
                result = grid_search(ticker, strategy_name)
            except Exception as e:
                logger.debug(f"[Updater] {ticker}/{strategy_name} grid_search 오류: {e}")
                skipped += 1
                continue

            if not result or result.get("sharpe", 0) < 1.0:
                skipped += 1
                continue

            current_sharpe = _get_current_sharpe(conn, ticker, strategy_name)
            if result["sharpe"] > current_sharpe:
                conn.execute(
                    """INSERT OR REPLACE INTO strategy_params
                       (ticker, strategy, params, sharpe, mdd, win_rate, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
                    (
                        ticker, strategy_name,
                        json.dumps(result["params"]),
                        result["sharpe"], result["mdd"], result["win_rate"],
                    ),
                )
                updated += 1
                logger.debug(
                    f"[Updater] {ticker}/{strategy_name} 업데이트: "
                    f"Sharpe {current_sharpe:.2f} → {result['sharpe']:.2f}"
                )
            else:
                skipped += 1

            if done % 20 == 0:
                logger.info(f"[Updater] {done}/{total} 완료 | 업데이트 {updated}건")

    conn.commit()
    conn.close()
    logger.info(f"[Updater] 증분 최적화 완료 — 업데이트 {updated}건 / 스킵 {skipped}건")
    return {"updated": updated, "skipped": skipped, "total": total}


# ── 피드백 기반 자동 처리 ────────────────────────────────────────────

def apply_feedback(feedback: dict) -> dict:
    """
    feedback_loop.analyze_recent_performance() 결과를 받아
    - critical 전략 → 일시정지
    - underperformer 전략 → 최근 종목에 대해 재최적화
    결과 요약 반환.
    """
    from learning.feedback_loop import get_recently_traded_tickers

    freed    = resume_expired_pauses()
    critical = feedback.get("critical", [])
    under    = feedback.get("underperformers", [])
    stats    = feedback.get("stats", {})

    # 위험 전략 일시정지
    newly_paused = []
    for name in critical:
        if not is_paused(name):
            v = stats.get(name, {})
            reason = (f"승률 {v.get('win_rate',0)*100:.0f}% "
                      f"({v.get('trades',0)}건) — 임계치({30}%) 미달")
            pause_strategy(name, reason)
            newly_paused.append(name)

    # 이탈 전략 재최적화
    opt_result = {"updated": 0, "skipped": 0}
    if under:
        tickers = get_recently_traded_tickers(days=feedback.get("period_days", 7))
        if not tickers:
            logger.info("[Updater] 최근 거래 종목 없음 — 재최적화 스킵")
        else:
            # 이탈 전략 중 일시정지되지 않은 것만
            active_under = [s for s in under if not is_paused(s)]
            if active_under:
                opt_result = run_incremental_optimization(tickers, strategies=active_under)

    return {
        "freed_pauses":   freed,
        "newly_paused":   newly_paused,
        "reoptimized":    under,
        "opt_updated":    opt_result.get("updated", 0),
        "currently_paused": [p["strategy"] for p in get_paused_strategies()],
    }


# ── 상태 요약 ────────────────────────────────────────────────────────

def get_status_summary() -> str:
    """대시보드 / 보고서용 현재 전략 상태 요약."""
    paused = get_paused_strategies()
    if not paused:
        return "일시정지 전략 없음"
    lines = ["일시정지 전략:"]
    for p in paused:
        lines.append(
            f"  {p['strategy']}: {p['reason'][:40]}  (until {p['paused_until']})"
        )
    return "\n".join(lines)
