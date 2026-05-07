"""
시장 감성 분석기

1차: Tavily 뉴스 수집 → Haiku로 JSON 감성 점수 산출
2차: Tavily API 없으면 키워드 기반 규칙 점수 fallback
"""
import logging

from ai.haiku_client import HaikuClient
from data.news_client import get_market_sentiment_news

logger = logging.getLogger(__name__)

_haiku = HaikuClient()

_POSITIVE = ["상승", "강세", "호재", "돌파", "신고가", "반등", "급등", "회복", "매수세", "외국인매수"]
_NEGATIVE = ["하락", "약세", "악재", "붕괴", "급락", "폭락", "위기", "매도세", "외국인매도", "패닉"]


def get_market_sentiment_score() -> dict:
    """
    시장 감성 점수 반환

    반환값:
      score : -1.0 ~ 1.0 (음수=부정, 0=중립, 양수=긍정)
      label : "긍정" | "중립" | "부정"
      reason: 한 줄 이유
      source: "haiku" | "keyword"
    """
    news = get_market_sentiment_news(max_results=5)

    if not news:
        return {"score": 0.0, "label": "중립", "reason": "뉴스 없음", "source": "default"}

    headlines = "\n".join(n.get("title", "") for n in news if n.get("title"))

    # ── Haiku 분석 (Tavily 키 있을 때) ──────────────────────
    if headlines and _haiku._ready:
        prompt = f"""다음 주식 시장 헤드라인을 보고 오늘 시장 분위기를 판단하세요.

{headlines}

응답 형식 (JSON만, 다른 텍스트 금지):
{{"score": -1에서 1 사이 소수, "label": "긍정 또는 중립 또는 부정", "reason": "한 줄 이유"}}"""

        result = _haiku.analyze_json(prompt, max_tokens=120)
        if "score" in result:
            result["source"] = "haiku"
            logger.info(f"[Sentiment] Haiku 분석: {result}")
            return result

    # ── 키워드 fallback ──────────────────────────────────────
    return _keyword_score(headlines)


def _keyword_score(text: str) -> dict:
    pos = sum(1 for kw in _POSITIVE if kw in text)
    neg = sum(1 for kw in _NEGATIVE if kw in text)
    total = pos + neg

    if total == 0:
        return {"score": 0.0, "label": "중립", "reason": "키워드 없음", "source": "keyword"}

    raw_score = (pos - neg) / total           # -1 ~ 1
    score     = round(raw_score, 2)
    label     = "긍정" if score > 0.2 else ("부정" if score < -0.2 else "중립")

    logger.info(f"[Sentiment] 키워드: 긍정={pos} 부정={neg} → {score}")
    return {
        "score":  score,
        "label":  label,
        "reason": f"긍정 키워드 {pos}개 / 부정 키워드 {neg}개",
        "source": "keyword",
    }


def should_skip_trading(sentiment: dict, threshold: float = -0.5) -> bool:
    """감성 점수가 임계값 이하이면 당일 매수 보류 권고"""
    return sentiment.get("score", 0) <= threshold
