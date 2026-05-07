import logging

import requests

from config.settings import TAVILY_API_KEY

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


def _search(query: str, max_results: int = 5) -> list[dict]:
    if not TAVILY_API_KEY:
        logger.warning("[News] TAVILY_API_KEY 미설정")
        return []
    try:
        resp = requests.post(
            TAVILY_URL,
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        logger.info(f"[News] '{query}' 검색 {len(results)}건")
        return results
    except Exception as e:
        logger.error(f"[News] 검색 실패 ({query}): {e}")
        return []


def search_stock_news(ticker_name: str, max_results: int = 5) -> list[dict]:
    """종목명 기준 최신 뉴스 (Tavily — 월 1,000건 무료)"""
    return _search(f"{ticker_name} 주식 뉴스 오늘", max_results)


def get_market_sentiment_news(max_results: int = 10) -> list[dict]:
    """코스피/코스닥 시장 분위기 뉴스"""
    return _search("코스피 코스닥 증시 오늘 전망", max_results)


def extract_headlines(results: list[dict]) -> list[str]:
    """뉴스 결과에서 제목만 추출"""
    return [r.get("title", "") for r in results if r.get("title")]
