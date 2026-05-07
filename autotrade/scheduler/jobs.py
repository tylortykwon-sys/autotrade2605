"""
스케줄러 작업 정의 — 시간대별 자동매매 로직
모든 job 함수는 cron_manager.py에서 APScheduler로 등록된다
"""
import logging
from datetime import datetime

from ai.sentiment import get_market_sentiment_score
from broker.order_manager import OrderManager
from data.collector import fetch_all_top
from data.dart_client import get_recent_disclosures
from data.database import save_portfolio_snapshot
from data.news_client import get_market_sentiment_news
from notify.report_builder import build_daily_report
from notify.telegram_bot import (send_circuit_breaker_alert, send_daily_report,
                                  send_message, send_sentiment_alert, send_system_alert)
from risk.circuit_breaker import CircuitBreaker
from strategy.larry_williams import LarryWilliamsStrategy, get_candidate_tickers
from strategy.scoring import get_buy_candidates

logger = logging.getLogger(__name__)

# ── 싱글톤 상태 객체 ──────────────────────────────────────────
order_mgr = OrderManager()
circuit   = CircuitBreaker()
lw_strat: LarryWilliamsStrategy | None = None
_disclosures: list[dict] = []   # 당일 공시 캐시


# ── 08:30 ────────────────────────────────────────────────────
def job_morning_prep():
    """장 시작 전 준비: 데이터 수집 + 공시/뉴스 확인"""
    global _disclosures
    logger.info("[Job] 08:30 — 장 시작 전 준비")
    send_message("장 시작 전 준비 중...")

    try:
        fetch_all_top(top_n=50)
        logger.info("[Job] 상위 50종목 OHLCV 수집 완료")
    except Exception as e:
        logger.error(f"[Job] 데이터 수집 오류: {e}")

    try:
        _disclosures = get_recent_disclosures(days=1)
        logger.info(f"[Job] 공시 {len(_disclosures)}건 수집")
    except Exception as e:
        logger.error(f"[Job] 공시 수집 오류: {e}")

    try:
        score = get_market_sentiment_score()
        logger.info(f"[Job] 시장 감성 점수: {score}")
        send_sentiment_alert(score["score"], score["label"], score["reason"])
    except Exception as e:
        logger.error(f"[Job] 감성 분석 오류: {e}")


# ── 09:00 ────────────────────────────────────────────────────
def job_market_open():
    """장 개시: Circuit Breaker 초기화 + 시작 자산 기록"""
    global lw_strat
    logger.info("[Job] 09:00 — 장 개시")
    circuit.reset()

    try:
        cash = order_mgr.client.get_cash()
        circuit.set_start(cash)
        lw_strat = LarryWilliamsStrategy(total_capital=cash, k=0.5)
        send_message(f"장 개시\n총 자산: {cash:,.0f}원\nDRY_RUN: {order_mgr.client.is_paper}")
        logger.info(f"[Job] 시작 자산: {cash:,.0f}원")
    except Exception as e:
        logger.error(f"[Job] 장 개시 처리 오류: {e}")


# ── 09:14 ────────────────────────────────────────────────────
def job_set_lw_triggers():
    """14분 레인지 확정 → 변동성 돌파 트리거가 설정"""
    if lw_strat is None:
        logger.warning("[Job] lw_strat 미초기화 — job_market_open 먼저 실행 필요")
        return

    logger.info("[Job] 09:14 — 변동성 돌파 트리거가 설정")
    try:
        candidates = get_candidate_tickers(top_n=10)
        for c in candidates:
            try:
                today = order_mgr.client.get_ohlcv_today(c["ticker"])
                # 09:00~09:14 고가/저가로 14분 레인지 계산
                lw_strat.set_trigger(
                    c["ticker"],
                    today["open"],
                    today["high"],
                    today["low"],
                )
            except Exception as e:
                logger.error(f"[Job] {c['ticker']} 트리거 설정 실패: {e}")

        send_message(f"변동성 돌파 감시 {len(candidates)}종목 설정 완료")
    except Exception as e:
        logger.error(f"[Job] 트리거 설정 오류: {e}")


# ── 09:15~09:30 (5분마다) ─────────────────────────────────────
def job_monitor_lw():
    """래리 윌리엄스 돌파 감시"""
    if lw_strat is None or circuit.is_triggered():
        return

    logger.info("[Job] LW 돌파 감시 실행")
    for ticker, trigger in list(lw_strat.triggers.items()):
        if order_mgr.has_position(ticker):
            continue
        try:
            today  = order_mgr.client.get_ohlcv_today(ticker)
            cur_p  = today["close"]
            cur_v  = today["volume"]
            avg_v  = cur_v  # 실제론 5일 평균 필요 — 단순화

            if lw_strat.should_buy(ticker, cur_p, cur_v, avg_v):
                from data.database import get_ohlcv
                from strategy.indicators import calc_atr
                import pandas as pd

                rows = get_ohlcv(ticker, 20)
                if rows:
                    df  = pd.DataFrame(rows)
                    for col in ["high", "low", "close"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    atr     = calc_atr(df["high"], df["low"], df["close"], 14).iloc[-1]
                    atr_pct = atr / today["close"] * 100
                else:
                    atr_pct = 1.5

                order_mgr.buy(ticker, strategy="LarryWilliams", atr_pct=atr_pct)
        except Exception as e:
            logger.error(f"[Job] LW 감시 {ticker} 오류: {e}")


# ── 10:00 ────────────────────────────────────────────────────
def job_scoring_buy():
    """멀티팩터 스코어링 기반 매수 실행"""
    if circuit.is_triggered():
        logger.info("[Job] Circuit Breaker 발동 — 스코어링 매수 스킵")
        return

    logger.info("[Job] 10:00 — 스코어링 매수 실행")
    try:
        candidates = get_buy_candidates(min_score=70.0, top_n=5)
        bought = 0
        for c in candidates:
            if order_mgr.available_slots() <= 0:
                break
            if order_mgr.has_position(c["ticker"]):
                continue
            # 공시 위험 종목 필터
            from data.dart_client import is_safe_to_buy
            from data.collector import get_ticker_name
            name = get_ticker_name(c["ticker"])
            if not is_safe_to_buy(name, _disclosures):
                logger.info(f"[Job] {c['ticker']} 위험 공시 — 매수 스킵")
                continue

            if order_mgr.buy(c["ticker"], strategy="MultiFactor", atr_pct=2.0):
                bought += 1

        logger.info(f"[Job] 스코어링 매수 완료: {bought}건")
    except Exception as e:
        logger.error(f"[Job] 스코어링 매수 오류: {e}")


# ── 10:00~14:00 (10분마다) ────────────────────────────────────
def job_monitor_positions():
    """보유 포지션 손절/익절 조건 감시"""
    if circuit.is_triggered():
        return

    try:
        closed = order_mgr.check_stop_conditions(
            stop_loss_pct=-0.02,
            take_profit_pct=0.03,
        )
        if closed:
            logger.info(f"[Job] 손절/익절 청산: {closed}")
        circuit.check(order_mgr.client)
    except Exception as e:
        logger.error(f"[Job] 포지션 감시 오류: {e}")


# ── 14:50 ────────────────────────────────────────────────────
def job_close_all():
    """장마감 전 전 종목 일괄 청산"""
    logger.info("[Job] 14:50 — 일괄 청산")
    if order_mgr.positions:
        count = len(order_mgr.positions)
        send_message(f"14:50 일괄 청산 실행 ({count}종목)")
        order_mgr.sell_all(reason="장마감_일괄청산")
    else:
        logger.info("[Job] 보유 포지션 없음 — 청산 불필요")

    if lw_strat:
        lw_strat.reset_day()


# ── 15:30 ────────────────────────────────────────────────────
def job_save_daily():
    """당일 포트폴리오 스냅샷 저장"""
    logger.info("[Job] 15:30 — 일일 스냅샷 저장")
    try:
        import json
        cash = order_mgr.client.get_cash()
        save_portfolio_snapshot({
            "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
            "total_value":   cash,
            "cash":          cash,
            "positions":     json.dumps(order_mgr.summary()["positions"]),
            "daily_pnl":     0,
        })
    except Exception as e:
        logger.error(f"[Job] 스냅샷 저장 오류: {e}")


# ── 15:35 ────────────────────────────────────────────────────
def job_daily_report():
    """일일 손익 보고서 생성 + AI 분석 + 텔레그램 발송"""
    logger.info("[Job] 15:35 — 일일 보고서 생성")
    try:
        report = build_daily_report()   # AI 코멘트 포함
        send_daily_report(report)
    except Exception as e:
        logger.error(f"[Job] 보고서 생성 오류: {e}")


# ── 23:00 (월 1일) ───────────────────────────────────────────
def job_monthly_optimize():
    """월 1회 전 전략 그리드서치 최적화 (야간 배치)"""
    logger.info("[Job] 월간 전략 최적화 시작")
    try:
        from data.collector import get_top_tickers
        from strategy.quant_engine import run_full_optimization
        tickers = get_top_tickers(top_n=30)
        saved = run_full_optimization(tickers)
        send_message(f"월간 최적화 완료: {saved}개 전략-종목 업데이트")
    except Exception as e:
        logger.error(f"[Job] 월간 최적화 오류: {e}")
        send_message(f"월간 최적화 오류: {e}")


# ── 08:00 (매주 월요일) ───────────────────────────────────────
def job_weekly_feedback():
    """주간 피드백 루프: 성과 분석 → 파라미터 자동 업데이트 → 알림"""
    logger.info("[Job] 주간 피드백 루프 시작")
    try:
        from learning.feedback_loop import analyze_recent_performance, generate_feedback_report
        from learning.param_updater import apply_feedback, get_status_summary

        feedback = analyze_recent_performance(days=7)
        result   = apply_feedback(feedback)
        report   = generate_feedback_report(days=7)

        # 파라미터 업데이트 결과 요약 추가
        summary_lines = [report, ""]
        if result["newly_paused"]:
            summary_lines.append(f"🛑 일시정지: {', '.join(result['newly_paused'])}")
        if result["freed_pauses"]:
            summary_lines.append(f"✅ 정지 해제: {', '.join(result['freed_pauses'])}")
        if result["opt_updated"] > 0:
            summary_lines.append(f"🔧 파라미터 갱신: {result['opt_updated']}건")
        paused_status = get_status_summary()
        if paused_status != "일시정지 전략 없음":
            summary_lines.append(paused_status)

        send_message("\n".join(summary_lines))
        logger.info(f"[Job] 주간 피드백 완료: {result}")
    except Exception as e:
        logger.error(f"[Job] 주간 피드백 오류: {e}")
        send_system_alert(f"주간 피드백 오류: {e}", level="ERROR")
