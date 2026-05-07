"""
APScheduler 스케줄러 등록 및 실행
KST 타임존 기준, 평일(월~금)만 실행
"""
import logging

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from scheduler.jobs import (
    job_close_all,
    job_daily_report,
    job_market_open,
    job_monitor_lw,
    job_monitor_positions,
    job_monthly_optimize,
    job_morning_prep,
    job_save_daily,
    job_scoring_buy,
    job_set_lw_triggers,
    job_weekly_feedback,
)

logger = logging.getLogger(__name__)
KST = pytz.timezone("Asia/Seoul")
WEEKDAYS = "mon-fri"


def _cron(hour: int, minute: int = 0, day_of_week: str = WEEKDAYS,
          hour_range: str | None = None, minute_interval: str | None = None) -> CronTrigger:
    kwargs: dict = {"timezone": KST, "day_of_week": day_of_week}
    if hour_range:
        kwargs["hour"] = hour_range
    else:
        kwargs["hour"] = hour
    kwargs["minute"] = minute_interval if minute_interval else minute
    return CronTrigger(**kwargs)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=KST)

    # 장 시작 전 준비
    scheduler.add_job(job_morning_prep,    _cron(8, 30),  id="morning_prep",    name="08:30 장 준비")

    # 장 개시
    scheduler.add_job(job_market_open,     _cron(9, 0),   id="market_open",     name="09:00 장 개시")

    # 14분 레인지 트리거가 설정
    scheduler.add_job(job_set_lw_triggers, _cron(9, 14),  id="lw_triggers",     name="09:14 LW 트리거")

    # 변동성 돌파 감시 (09:15~09:30, 5분마다)
    scheduler.add_job(
        job_monitor_lw,
        CronTrigger(day_of_week=WEEKDAYS, hour=9, minute="15,20,25,30", timezone=KST),
        id="monitor_lw", name="09:15~09:30 LW 감시",
    )

    # 스코어링 매수
    scheduler.add_job(job_scoring_buy,     _cron(10, 0),  id="scoring_buy",     name="10:00 스코어링 매수")

    # 포지션 손절/익절 감시 (10:00~14:00, 10분마다)
    scheduler.add_job(
        job_monitor_positions,
        CronTrigger(day_of_week=WEEKDAYS, hour="10-14", minute="*/10", timezone=KST),
        id="monitor_pos", name="10~14시 포지션 감시",
    )

    # 장마감 일괄 청산
    scheduler.add_job(job_close_all,       _cron(14, 50), id="close_all",       name="14:50 일괄 청산")

    # 일일 스냅샷 저장
    scheduler.add_job(job_save_daily,      _cron(15, 30), id="save_daily",       name="15:30 스냅샷 저장")

    # 일일 보고서
    scheduler.add_job(job_daily_report,    _cron(15, 35), id="daily_report",    name="15:35 일일 보고서")

    # 월간 최적화 (매월 1일 23:00)
    scheduler.add_job(
        job_monthly_optimize,
        CronTrigger(day=1, hour=23, minute=0, timezone=KST),
        id="monthly_opt", name="월 1일 23:00 최적화",
    )

    # 주간 피드백 루프 (매주 월요일 08:00)
    scheduler.add_job(
        job_weekly_feedback,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=KST),
        id="weekly_feedback", name="월요일 08:00 주간 피드백",
    )

    scheduler.start()
    _log_jobs(scheduler)
    logger.info("[Scheduler] 스케줄러 시작 완료")
    return scheduler


def _log_jobs(scheduler: BackgroundScheduler):
    logger.info("[Scheduler] 등록된 작업 목록:")
    for job in scheduler.get_jobs():
        logger.info(f"  {job.name} → 다음 실행: {job.next_run_time}")


def stop_scheduler(scheduler: BackgroundScheduler):
    scheduler.shutdown(wait=False)
    logger.info("[Scheduler] 스케줄러 종료")
