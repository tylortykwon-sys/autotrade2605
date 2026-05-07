"""
autotrade — 국내주식 자동매매 시스템 진입점
Scenario B: Hetzner VPS + Claude Haiku
"""
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/trading.log"),
    ],
)
logger = logging.getLogger("main")


def main():
    from config.settings import DRY_RUN, DB_PATH
    logger.info("=" * 50)
    logger.info("autotrade 시스템 시작")
    logger.info(f"모드: {'모의투자(DRY_RUN)' if DRY_RUN else '실전투자'}")
    logger.info(f"DB: {DB_PATH}")

    from data.database import init_db
    init_db()
    logger.info("DB 초기화 완료")

    from scheduler.cron_manager import start_scheduler
    scheduler = start_scheduler()
    logger.info("스케줄러 시작 완료 — 평일 08:30~15:35 자동 실행")

    try:
        import time
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        from scheduler.cron_manager import stop_scheduler
        stop_scheduler(scheduler)
        logger.info("시스템 종료")


if __name__ == "__main__":
    Path("logs/reports").mkdir(parents=True, exist_ok=True)
    main()
