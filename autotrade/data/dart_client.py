import logging
from datetime import datetime, timedelta

import requests

from config.settings import DART_API_KEY

logger = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api"

DANGER_KEYWORDS = ["유상증자", "전환사채", "횡령", "배임", "상장폐지", "자본잠식", "주식병합", "감자"]
POSITIVE_KEYWORDS = ["자사주취득", "배당", "영업이익", "매출", "실적", "자사주소각"]


def get_recent_disclosures(corp_code: str = None, days: int = 1) -> list[dict]:
    """최근 N일 공시 목록 조회"""
    if not DART_API_KEY:
        logger.warning("[DART] API 키 미설정 — .env의 DART_API_KEY 확인")
        return []

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    params = {
        "crtfc_key": DART_API_KEY,
        "bgn_de": start_date,
        "end_de": end_date,
        "sort": "date",
        "sort_mth": "desc",
        "page_count": 40,
    }
    if corp_code:
        params["corp_code"] = corp_code

    try:
        resp = requests.get(f"{BASE_URL}/list.json", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "000":
            logger.warning(f"[DART] 응답 오류: {data.get('message')}")
            return []
        disclosures = data.get("list", [])
        logger.info(f"[DART] 공시 {len(disclosures)}건 조회")
        return disclosures
    except Exception as e:
        logger.error(f"[DART] 조회 실패: {e}")
        return []


def is_safe_to_buy(ticker_name: str, disclosures: list[dict]) -> bool:
    """해당 종목의 위험 공시 여부 확인 (True=매수 가능)"""
    for d in disclosures:
        corp = d.get("corp_name", "")
        title = d.get("report_nm", "")
        if ticker_name in corp:
            for kw in DANGER_KEYWORDS:
                if kw in title:
                    logger.warning(f"[DART] {ticker_name} 위험 공시 감지: {title}")
                    return False
    return True


def get_positive_tickers(disclosures: list[dict]) -> list[str]:
    """긍정 공시가 있는 종목명 목록 반환"""
    result = []
    for d in disclosures:
        title = d.get("report_nm", "")
        corp = d.get("corp_name", "")
        for kw in POSITIVE_KEYWORDS:
            if kw in title and corp not in result:
                result.append(corp)
    return result
