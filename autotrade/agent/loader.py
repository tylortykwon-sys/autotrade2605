"""
에이전트 지침 파일 로더
agents.md / soul.md / memory.md를 읽어 AI 프롬프트 컨텍스트로 반환
"""
from pathlib import Path

AGENT_DIR = Path(__file__).parent


def load_agents() -> str:
    return (AGENT_DIR / "agents.md").read_text(encoding="utf-8")


def load_soul() -> str:
    return (AGENT_DIR / "soul.md").read_text(encoding="utf-8")


def load_memory() -> str:
    return (AGENT_DIR / "memory.md").read_text(encoding="utf-8")


def build_system_prompt() -> str:
    """AI 분석 호출 시 사용할 통합 시스템 프롬프트"""
    return "\n\n---\n\n".join([
        load_soul(),
        load_agents(),
        "## 현재 학습 기억\n" + load_memory(),
    ])


def update_memory_section(section: str, content: str):
    """memory.md의 특정 섹션 업데이트"""
    mem_path = AGENT_DIR / "memory.md"
    text = mem_path.read_text(encoding="utf-8")

    marker = f"### {section}"
    if marker not in text:
        text += f"\n\n{marker}\n{content}\n"
    else:
        lines = text.split("\n")
        result, in_section, replaced = [], False, False
        for line in lines:
            if line.strip() == marker:
                in_section = True
                result.append(line)
                result.append(content)
                replaced = True
                continue
            if in_section and line.startswith("###") and line.strip() != marker:
                in_section = False
            if not in_section or not replaced:
                result.append(line)
        text = "\n".join(result)

    mem_path.write_text(text, encoding="utf-8")
