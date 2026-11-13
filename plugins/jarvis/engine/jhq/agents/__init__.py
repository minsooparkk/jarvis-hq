"""에이전트 층. 데몬·명령·설치는 `claude`·`codex` 실행 파일을 직접 알지 않고 여기서 고른 Agent 를 쓴다.

config.json 의 agent: claude(기본, 예전 설치 그대로) | codex.
숨기는 것: 세션 띄우기·이어 가기·출력 읽기(진행 글·도구 이름·마지막 답), 홈에서 읽을 파일 맞추기(Codex 의 AGENTS.md),
문지기·권한을 세션에 거는 방법, 점검 항목, 문지기 보장(Claude 대비 같음·약함·강함).
메신저 층(jhq.messengers)·OS 층(jhq.platform)과 같은 모양이다. 표준 라이브러리만 쓴다.
"""

from .base import STALL, Agent, Reply, StallError, agent_env  # noqa: F401

NAMES = ("claude", "codex")
DISPLAY = {"claude": "Claude Code", "codex": "Codex"}


class UnknownAgent(ValueError):
    pass


def kind(cfg):
    a = str((cfg or {}).get("agent") or "claude").strip().lower()
    if a not in NAMES:
        raise UnknownAgent(f"모르는 에이전트입니다: {a} (claude · codex)")
    return a


def get(cfg_or_name=None, **kw):
    name = cfg_or_name if isinstance(cfg_or_name, str) else kind(cfg_or_name)
    if name == "codex":
        from .codex import Codex
        return Codex(**kw)
    if name == "claude":
        from .claude import Claude
        return Claude()
    raise UnknownAgent(f"모르는 에이전트입니다: {name} (claude · codex)")


def runner(cfg):
    """데몬이 부를 함수(cfg, paths, prompt, session, resume, context, …) → Reply."""
    return get(cfg).run
