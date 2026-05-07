"""
Claude Haiku API 클라이언트

비용 제어:
  - 일일 호출 횟수 제한 (MAX_DAILY_CALLS=5)
  - max_tokens 최소화 (기본 300)
  - API 키 미설정 시 fallback 텍스트 반환 (에러 없이 작동)
"""
import json
import logging
import os
from datetime import date
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

_CALL_LOG = Path(__file__).parent / ".call_log.json"   # 일별 호출 횟수 기록


class HaikuClient:
    MAX_DAILY_CALLS = int(os.getenv("AI_MAX_DAILY_CALLS", "5"))

    def __init__(self):
        api_key    = os.getenv("ANTHROPIC_API_KEY", "")
        self.model = os.getenv("AI_ANALYSIS_MODEL", "claude-haiku-4-5-20251001")
        self._ready = bool(api_key)
        if self._ready:
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            logger.warning("[Haiku] ANTHROPIC_API_KEY 미설정 — fallback 모드")

    # ── 호출 제한 ─────────────────────────────────────────────

    def _load_call_log(self) -> dict:
        if _CALL_LOG.exists():
            try:
                return json.loads(_CALL_LOG.read_text())
            except Exception:
                pass
        return {}

    def _save_call_log(self, log: dict):
        _CALL_LOG.write_text(json.dumps(log))

    def _check_limit(self) -> bool:
        """일일 호출 한도 확인. 초과 시 False 반환."""
        today = str(date.today())
        log   = self._load_call_log()
        count = log.get(today, 0)
        if count >= self.MAX_DAILY_CALLS:
            logger.warning(f"[Haiku] 일일 호출 한도 초과: {count}/{self.MAX_DAILY_CALLS}")
            return False
        log[today] = count + 1
        self._save_call_log(log)
        return True

    def daily_calls_used(self) -> int:
        today = str(date.today())
        return self._load_call_log().get(today, 0)

    # ── 분석 실행 ─────────────────────────────────────────────

    def analyze(self, prompt: str, system: str = "",
                max_tokens: int = 300) -> str:
        """Haiku 분석 실행. API 미설정·한도 초과 시 fallback 반환."""
        if not self._ready:
            return f"[Haiku fallback] ANTHROPIC_API_KEY 미설정 — 분석 불가\n입력: {prompt[:80]}..."

        if not self._check_limit():
            return f"[Haiku] 일일 한도({self.MAX_DAILY_CALLS}회) 도달 — 내일 재시도"

        try:
            kwargs: dict = {
                "model":      self.model,
                "max_tokens": max_tokens,
                "messages":   [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system

            resp = self.client.messages.create(**kwargs)
            result = resp.content[0].text
            logger.info(f"[Haiku] 분석 완료 ({len(result)}자) "
                        f"호출: {self.daily_calls_used()}/{self.MAX_DAILY_CALLS}")
            return result

        except anthropic.APIStatusError as e:
            logger.error(f"[Haiku] API 오류 {e.status_code}: {e.message}")
            return f"[Haiku 오류] {e.message}"
        except Exception as e:
            logger.error(f"[Haiku] 예외: {e}")
            return f"[Haiku 예외] {e}"

    def analyze_json(self, prompt: str, system: str = "",
                     max_tokens: int = 200) -> dict:
        """JSON 응답 강제. 파싱 실패 시 빈 dict 반환."""
        raw = self.analyze(prompt, system, max_tokens)
        # 마크다운 코드블록 제거
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:-1])
        try:
            return json.loads(raw)
        except Exception:
            logger.warning(f"[Haiku] JSON 파싱 실패: {raw[:100]}")
            return {"raw": raw}
