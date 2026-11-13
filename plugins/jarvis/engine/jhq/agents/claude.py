"""Claude Code(`claude -p … --output-format stream-json`). 지금까지의 동작 그대로다(기본 에이전트).

- 대화: 새 대화는 `--session-id <id>`, 이어 가기는 `--resume <id>`(id 는 데몬이 정함).
- 이번 실행에만 더할 지시: `--append-system-prompt`.
- 규칙: 홈의 CLAUDE.md(@ 줄로 rules/ 를 불러옴). 스킬: 플러그인 `jarvis:…` 와 홈의 .claude/skills(→ ../skills).
- 권한·문지기: `jarvis perms build` 가 만드는 <홈>/.claude/settings.json(허용·잠금 거부·PreToolUse 훅 gate.py)과
  플러그인의 hooks/hooks.json(같은 gate.py).
"""

import json
from pathlib import Path

from .base import STALL, Agent, Reply, agent_env, stream


class Claude(Agent):
    name = "claude"
    display = "Claude Code"
    home_file = "CLAUDE.md"
    exe = "claude"

    def find(self, plat):
        return plat.find_claude()

    def configured(self, cfg):
        return (cfg or {}).get("claude") or None

    def argv(self, cfg, plat):
        return plat.claude_argv(self.path(cfg, plat))

    def command(self, cfg, plat, prompt, session, resume=False, context=""):
        stdin_prompt = plat.prompt_on_stdin  # 윈도: 명령줄 길이 한도·따옴표 처리 때문에 질문은 표준입력으로
        cmd = self.argv(cfg, plat) + ["-p"] + ([] if stdin_prompt else [prompt]) + [
            "--output-format", "stream-json", "--verbose", "--resume" if resume else "--session-id", session]
        if context:
            cmd += ["--append-system-prompt", context]
        return cmd, (prompt if stdin_prompt else None)

    def run(self, cfg, paths, prompt, session, resume=False, context="", timeout=None, on_text=None, on_tool=None,
            on_tick=None, register=None, stall=STALL):
        """claude -p 를 stream-json 으로 돌려 최종 답을 돌려준다. 도구 사이의 글은 on_text, 도구 이름은 on_tool 로 넘긴다."""
        from .. import config
        timeout = timeout or int(cfg.get("agent_timeout_min") or 20) * 60
        cmd, stdin_text = self.command(cfg, config.plat(), prompt, session, resume, context)
        st = {"final": None, "is_error": False, "pending": []}

        def on_line(ln):
            try:
                ev = json.loads(ln)
            except ValueError:
                return
            if ev.get("type") == "assistant":
                for b in (ev.get("message") or {}).get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and str(b.get("text") or "").strip():
                        st["pending"].append(b["text"].strip())
                    elif b.get("type") == "tool_use":
                        if on_text:
                            for t in st["pending"]:
                                on_text(t)
                        st["pending"] = []
                        if on_tool:
                            on_tool(str(b.get("name") or ""))
            elif ev.get("type") == "result":
                st["final"], st["is_error"] = ev.get("result"), bool(ev.get("is_error"))

        code, err, stopped = stream(cmd, paths.home, agent_env(cfg), on_line, stdin_text, timeout, stall, on_tick,
                                    register, who="Claude")
        if stopped:
            raise RuntimeError("멈췄습니다(/stop)")
        if code != 0 or st["final"] is None or st["is_error"]:
            raise RuntimeError(f"claude 종료 코드 {code}: {(str(st['final'] or '') + err)[-300:].strip()}")
        return Reply(str(st["final"]).strip(), session)

    def checks(self, cfg, paths, plat):
        p = self.configured(cfg) or ""
        return [(f"claude 명령({p})", bool(p) and Path(p).exists(),
                 "Claude Code 를 설치했거나 자리가 바뀌었으면 설치(스킬 jarvis:setup)를 다시 돌리세요(config.json 의 claude 를 지금 자리로)")]

    def guard(self, cfg=None):
        return [("문지기(gate.py)", "기준", "PreToolUse 훅: Bash·PowerShell·Read·Edit·Write·MCP 도구를 쓰기 직전에 본다"),
                ("권한", "기준", "<홈>/.claude/settings.json 의 허용·잠금 거부(jarvis perms build)")]

    def doctor_hint(self):
        return "이 컴퓨터에서 Claude Code 를 열고 /jarvis:doctor 를 돌려 주세요"
