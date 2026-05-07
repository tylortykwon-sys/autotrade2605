"""
시장 감성 분석기 — Phase 7에서 Haiku 연동 완성 예정
현재: 뉴스 키워드 기반 단순 점수
"""
import logging

from data.news_client import get_market_sentiment_news

logger = logging.getLogger(__name__)

POSITIVE_KW = ["상승", "강세", "호재", "돌파", "신고가", "매수", "급등", "회복"]
NEGATIVE_KW = ["하락", "약세", "악재", "붕괴", "매도", "급락", "폭락", "위기"]


def get_market_sentiment_score() -> float:
    """시장 감성 점수 반환 (0~100, 50=중립)"""
    results = get_market_sentiment_news(max_results=10)
    if not results:
        return 50.0

    pos, neg = 0, 0
    for r in results:
        text = (r.get("title", "") + " " + r.get("content", ""))
        pos += sum(1 for kw in POSITIVE_KW if kw in text)
        neg += sum(1 for kw in NEGATIVE_KW if kw in text)

    total = pos + neg
    if total == 0:
        return 50.0

    score = round((pos / total) * 100, 1)
    logger.info(f"[Sentiment] 시장 감성 점수: {score} (긍정:{pos} 부정:{neg})")
    return score
