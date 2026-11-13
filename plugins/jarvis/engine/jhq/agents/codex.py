"""OpenAI Codex CLI(`codex exec --json`). config.json 의 agent 가 codex 일 때 쓴다.

확인한 판: codex-cli 0.165.0(docs/codex-확인할-것.md). Claude 쪽과 다른 점과 맞춘 방법
- 대화: 새 대화는 `codex exec`, 이어 가기는 `codex exec resume <id>`. id 는 Codex 가 정해 첫 사건(thread.started)에 준다.
  데몬은 Reply.session 으로 받아 그 대화의 id 로 적는다.
- 질문은 늘 표준입력으로(`-`). '-' 로 시작하는 질문이 옵션으로 읽히지 않고, 명령줄 길이 한도도 없다.
- 이번 실행에만 더할 지시: `-c developer_instructions=…`(Claude 의 --append-system-prompt 자리).
- 규칙: Codex 는 AGENTS.md 를 읽고 @ 줄(불러오기)을 모른다. 그래서 홈의 CLAUDE.md 를 원본으로 두고 @ 줄을 풀어
  AGENTS.md 를 만든다(sync_home. 데몬이 띄울 때마다 바뀐 것만 다시 씀). AGENTS.md 는 고치지 않는다.
- 스킬: 플러그인 jarvis(같은 저장소를 Codex 플러그인으로 넣음, 스킬 이름 jarvis:…)와 홈의 .agents/skills(→ ../skills).
- MCP: 엔진의 mcp.json(플러그인 .mcp.json 사본)을 세션마다 `-c mcp_servers.<이름>.url=…` 로 준다.
- 문지기: 세션마다 `-c hooks.PreToolUse=…` 로 엔진 사본 gate.py 를 걸고 `--dangerously-bypass-hook-trust` 로 늘 돌린다
  (Codex 는 검토(/hooks)하지 않은 훅을 건너뛴다). 세션 시작 맥락(session_start.py)은 Claude 와 같이 플러그인 훅으로만. 샌드박스 workspace-write(쓰기는 홈·임시 폴더만, 네트워크는 기본 꺼짐),
  승인 정책 never(샌드박스 밖으로 나가는 요청은 묻지 않고 거절). ChatGPT 앱·브라우저·컴퓨터 사용 기능은 끈다.
  Claude 와 다른 점은 guard() 표와 docs/보안-모델.md 에 그대로 적는다.
"""

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from .base import STALL, Agent, Reply, agent_env, stream

PLUGIN_ID = "jarvis@jarvis-hq"
MARKER = "<!-- jarvis: 이 파일은 CLAUDE.md 에서 저절로 만든다(@ 줄을 풀어 넣음). 고치려면 CLAUDE.md 나 rules/ 를 고친다. jarvis agent sync -->"
GATE_MATCHER = "Bash|apply_patch|Edit|Write|write_stdin|mcp__.*"
OFF_FEATURES = ("apps", "browser_use", "computer_use", "in_app_browser")  # 훅이 거는지 확인 못 한 길: 끈다
DOC_MAX = 262144  # AGENTS.md 를 다 읽게(기본 32KiB 는 사용자 전역 AGENTS.md 와 합쳐 넘을 수 있음)
DEFAULTS = {"path": None, "network": False, "model": "", "reasoning": "", "writable_roots": [], "apps": False}
TOOLS = {"command_execution": "Bash", "file_change": "Edit", "web_search": "WebSearch", "collab_tool_call": "Agent"}
INCLUDE = re.compile(r"^@(\S+)\s*$")


def toml(v):
    """-c 값으로 넘길 TOML 한 토막(글은 JSON 꼴 따옴표, 표는 인라인 표)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {toml(x)}" for k, x in v.items()) + "}"
    raise TypeError(f"TOML 로 못 바꿈: {type(v)}")


def opts(cfg):
    o = dict(DEFAULTS)
    c = (cfg or {}).get("codex")
    if isinstance(c, dict):
        o.update({k: v for k, v in c.items() if v is not None})
    elif isinstance(c, str) and c:  # 예전 꼴(실행 파일 자리만)
        o["path"] = c
    return o


def engine_file(*parts):
    """엔진 사본의 파일(설치된 엔진: <엔진>/engine/…, 저장소에서 돌 때: 플러그인 뿌리의 같은 자리)."""
    from .. import config
    p = config.ENGINE_ROOT.joinpath(*parts)
    if p.exists():
        return p
    alt = {"mcp.json": ".mcp.json"}.get(parts[-1], parts[-1])
    return config.ENGINE_ROOT.parent.joinpath(*parts[:-1], alt)


def mcp_servers():
    """{이름: url}: 플러그인에 실린 HTTP MCP 서버(엔진 mcp.json)."""
    try:
        doc = json.loads(engine_file("mcp.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for name, s in (doc.get("mcpServers") or {}).items():
        if isinstance(s, dict) and s.get("url") and re.match(r"^[A-Za-z0-9_-]+$", name):
            out[name] = str(s["url"])
    return out


def render_agents_md(home):
    """CLAUDE.md 의 @ 줄(@rules/…·@RULES.md)을 그 파일 내용으로 풀어 AGENTS.md 글을 만든다. CLAUDE.md 가 없으면 None."""
    home = Path(home)
    try:
        src = (home / "CLAUDE.md").read_text(encoding="utf-8")
    except OSError:
        return None
    out = [MARKER, ""]
    for line in src.splitlines():
        m = INCLUDE.match(line.strip())
        if not m:
            out.append(line)
            continue
        rel = m.group(1)
        p = (home / rel)
        try:
            body = p.read_text(encoding="utf-8").strip("\n")
        except OSError:
            out.append(f"(불러올 파일이 없음: {rel})")
            continue
        out += [f"<!-- {rel} -->", body, ""]
    return "\n".join(out).rstrip("\n") + "\n"


def sync_agents_md(paths):
    """AGENTS.md 를 CLAUDE.md 에 맞춘다. 돌려주는 것: '만듦'·'새로 씀'·'같음'·'원본 없음'(+ 옮긴 옛 파일)."""
    text = render_agents_md(paths.home)
    if text is None:
        return "원본 없음(CLAUDE.md)"
    dest = Path(paths.home) / "AGENTS.md"
    if dest.exists():
        old = dest.read_text(encoding="utf-8", errors="replace")
        if old == text:
            return "같음"
        if not old.startswith(MARKER):  # 손으로 만든 AGENTS.md: 지우지 않고 옮겨 둔다
            back = Path(paths.state) / "backup" / time.strftime("%Y%m%d-%H%M%S")
            back.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest, back / "AGENTS.md")
            dest.write_text(text, encoding="utf-8")
            return f"새로 씀(옛 AGENTS.md 는 {back / 'AGENTS.md'})"
        dest.write_text(text, encoding="utf-8")
        return "새로 씀"
    dest.write_text(text, encoding="utf-8")
    return "만듦"


class Codex(Agent):
    name = "codex"
    display = "Codex"
    home_file = "AGENTS.md"
    exe = "codex"

    def __init__(self, run=None):
        self._run = run  # 시험: codex 명령(plugin list 등)을 가짜로

    # ---------- 실행 파일 ----------
    def find(self, plat):
        env_path = plat.environ.get("PATH")
        cands = [shutil.which("codex", path=env_path)]
        if plat.name == "windows":
            appdata = plat.environ.get("APPDATA")
            cands += [os.path.join(appdata, "npm", "codex.cmd") if appdata else None, str(plat.user_bin() / "codex.exe")]
        else:
            cands.append(str(plat.user_bin() / "codex"))
        for c in cands:
            if c and os.path.exists(c):
                return c
        return None

    def configured(self, cfg):
        return opts(cfg).get("path") or None

    def argv(self, cfg, plat):
        """윈도 npm 의 codex.cmd 는 받은 글이 cmd 를 거치며 깨질 수 있어 그 뒤의 진짜 프로그램을 부른다
        (node + 패키지의 bin/codex.js, 없으면 패키지 안 codex.exe). 맥은 그대로(npm 의 codex 는 node 스크립트라 PATH 에 node 가 있어야 함)."""
        p = str(self.path(cfg, plat))
        if plat.name != "windows" or not p.lower().endswith((".cmd", ".ps1", ".bat")):
            return [p]
        pkg = Path(p).parent / "node_modules" / "@openai" / "codex"
        js = pkg / "bin" / "codex.js"
        node = Path(p).parent / "node.exe"
        node = str(node) if node.exists() else shutil.which("node", path=plat.environ.get("PATH"))
        if js.exists() and node:
            return [node, str(js)]
        for exe in sorted(pkg.glob("node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe")) + \
                sorted(pkg.parent.glob("codex-win32-*/vendor/*/bin/codex.exe")):
            return [str(exe)]
        from ..platform import Unsupported
        raise Unsupported(f"{p} 뒤의 Codex 프로그램을 찾지 못했습니다. `npm install -g @openai/codex` 로 다시 깔아 주세요.")

    def path_dirs(self, cfg, plat):
        """세션 PATH 앞에 더할 폴더: codex 가 있는 폴더(npm 의 codex 는 같은 폴더의 node 로 돈다)."""
        p = self.configured(cfg) or self.find(plat)
        return [str(Path(p).parent)] if p and os.path.isabs(str(p)) else []

    # ---------- 세션 설정 ----------
    def hook_command(self, plat, script):
        gate = engine_file("hooks", script)
        if plat.name == "windows":
            return f'"{plat.console_python(sys.executable)}" "{gate}"'
        return f"/usr/bin/python3 {shlex_quote(str(gate))}"

    def writable_roots(self, cfg, paths):
        roots = list(opts(cfg).get("writable_roots") or [])
        try:
            user = json.loads(Path(paths.permissions).read_text(encoding="utf-8"))
            roots += list(user.get("additionalDirectories") or [])
        except (OSError, ValueError):
            pass
        return list(dict.fromkeys(os.path.expanduser(str(r)) for r in roots if r))

    def overrides(self, cfg, paths, plat, context="", approval="never"):
        """세션마다 줄 `-c 열쇠=값` 목록(사용자 ~/.codex/config.toml 은 바꾸지 않는다)."""
        o = opts(cfg)
        kv = [("sandbox_mode", "workspace-write"), ("approval_policy", approval),
              ("sandbox_workspace_write.network_access", bool(o.get("network"))),
              ("project_doc_max_bytes", DOC_MAX), ("features.hooks", True)]
        roots = self.writable_roots(cfg, paths)
        if roots:
            kv.append(("sandbox_workspace_write.writable_roots", roots))
        if not o.get("apps"):
            kv += [(f"features.{f}", False) for f in OFF_FEATURES]
        kv.append(("hooks.PreToolUse", [{"matcher": GATE_MATCHER, "hooks": [
            {"type": "command", "command": self.hook_command(plat, "gate.py"), "timeout": 20}]}]))
        for name, url in mcp_servers().items():
            # 플러그인에 실린 읽기 전용 조회 서버. approve = 도구마다 묻지 않음(묻는 도구는 never 정책에서 쓰이지 못할 수 있어)
            kv += [(f"mcp_servers.{name}.url", url), (f"mcp_servers.{name}.default_tools_approval_mode", "approve")]
        if o.get("model"):
            kv.append(("model", str(o["model"])))
        if o.get("reasoning"):
            kv.append(("model_reasoning_effort", str(o["reasoning"])))
        if context:
            kv.append(("developer_instructions", context))
        args = []
        for k, v in kv:
            args += ["-c", f"{k}={toml(v)}"]
        return args

    def command(self, cfg, plat, paths, session, resume=False, context=""):
        cmd = self.argv(cfg, plat) + ["exec"] + (["resume"] if resume else []) + [
            "--json", "--skip-git-repo-check", "--dangerously-bypass-hook-trust"] + self.overrides(cfg, paths, plat, context)
        return cmd + ([session] if resume else []) + ["-"]

    def interactive_argv(self, cfg, paths, plat):
        """`jarvis agent open`: 홈에서 대화형 Codex 를 데몬과 같은 울타리로 연다(승인 정책만 on-request)."""
        return self.argv(cfg, plat) + ["--dangerously-bypass-hook-trust", "-C", str(paths.home)] + \
            self.overrides(cfg, paths, plat, approval="on-request")

    # ---------- 실행 ----------
    def run(self, cfg, paths, prompt, session, resume=False, context="", timeout=None, on_text=None, on_tool=None,
            on_tick=None, register=None, stall=STALL):
        from .. import config
        plat = config.plat()
        timeout = timeout or int(cfg.get("agent_timeout_min") or 20) * 60
        try:
            sync_agents_md(paths)
        except OSError:
            pass
        cmd = self.command(cfg, plat, paths, session, resume, context)
        st = {"thread": None, "last": None, "pending": [], "failed": None, "done": False, "errors": []}

        def on_line(ln):
            try:
                ev = json.loads(ln)
            except ValueError:
                return
            t = ev.get("type")
            item = ev.get("item") if isinstance(ev.get("item"), dict) else {}
            kind = item.get("type")
            if t == "thread.started":
                st["thread"] = ev.get("thread_id") or st["thread"]
            elif t == "item.started" and (kind in TOOLS or kind == "mcp_tool_call"):
                if on_text:
                    for x in st["pending"]:
                        on_text(x)
                st["pending"] = []
                if on_tool:
                    on_tool(f"mcp__{item.get('server') or '?'}__{item.get('tool') or '?'}" if kind == "mcp_tool_call"
                            else TOOLS[kind])
            elif t == "item.completed" and kind == "agent_message":
                text = str(item.get("text") or "").strip()
                if text:
                    st["pending"].append(text)
                    st["last"] = text
            elif t == "item.completed" and kind == "error":
                st["errors"].append(str(item.get("message") or ""))
            elif t == "turn.completed":
                st["done"] = True
            elif t == "turn.failed":
                st["failed"] = str((ev.get("error") or {}).get("message") or "실패")
            elif t == "error":
                st["errors"].append(str(ev.get("message") or ""))

        code, err, stopped = stream(cmd, paths.home, agent_env(cfg, self.path_dirs(cfg, plat)), on_line, prompt, timeout,
                                    stall, on_tick, register, who="Codex")
        if stopped:
            raise RuntimeError("멈췄습니다(/stop)")
        if code != 0 or st["failed"] or not st["done"] or st["last"] is None:
            why = st["failed"] or next((e for e in reversed(st["errors"]) if e and "bypass-hook-trust" not in e), "") or err
            raise RuntimeError(f"codex 종료 코드 {code}: {str(why)[-300:].strip()}")
        return Reply(st["last"], st["thread"] or session)

    # ---------- 홈 ----------
    def prepare_home(self, paths, cfg=None, plat=None):
        from .. import config
        made = []
        r = sync_agents_md(paths)
        if r != "같음":
            made.append(f"AGENTS.md {r}")
        link = (plat or config.plat()).link_dir(Path(paths.home) / ".agents" / "skills", "../skills")
        if link:
            made.append(link)
        return made

    # ---------- 점검 ----------
    def cmd(self, cfg, plat, *args, timeout=60):
        argv = self.argv(cfg, plat) + list(args)
        env = agent_env(cfg or {}, self.path_dirs(cfg, plat)) if not self._run else None
        if self._run:
            return self._run(argv)
        return plat.cmd(argv, timeout=timeout, env=env)

    def version(self, cfg, plat):
        try:
            r = self.cmd(cfg, plat, "--version", timeout=30)
            return (r.stdout or "").strip() if r.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    def plugin_state(self, cfg, plat):
        """'installed' · 'missing' · 'unknown'(codex 를 못 부름)."""
        try:
            r = self.cmd(cfg, plat, "plugin", "list", "--json")
            doc = json.loads(r.stdout or "{}")
        except Exception:  # noqa: BLE001
            return "unknown"
        for p in doc.get("installed") or []:
            if p.get("pluginId") == PLUGIN_ID and p.get("installed") and p.get("enabled", True):
                return "installed"
        return "missing"

    def plugin_plan(self, source):
        """Codex 에 플러그인 jarvis 를 넣는 명령(source: 저장소 뿌리 자리 또는 owner/repo)."""
        return [["plugin", "marketplace", "add", str(source)], ["plugin", "add", PLUGIN_ID]]

    def checks(self, cfg, paths, plat):
        p = self.configured(cfg) or ""
        home = Path(paths.home)
        agents = home / "AGENTS.md"
        want = render_agents_md(home)
        out = [(f"codex 명령({p})", bool(p) and Path(p).exists(),
                "Codex CLI 를 깔고(npm install -g @openai/codex) 설치를 다시 돌리세요(config.json 의 codex.path)"),
               ("홈 AGENTS.md(CLAUDE.md 에서 만듦)", agents.exists() and want is not None
                and agents.read_text(encoding="utf-8", errors="replace") == want, "jarvis agent sync"),
               ("홈 .agents/skills(→ ../skills)", (home / ".agents" / "skills").exists()
                or (home / ".agents" / "skills").is_symlink(), "jarvis agent sync")]
        state = self.plugin_state(cfg, plat) if p else "unknown"
        out.append(("Codex 플러그인 jarvis(스킬·MCP·훅)", state == "installed",
                    "codex plugin marketplace add minsooparkk/jarvis-hq 다음에 codex plugin add jarvis@jarvis-hq"
                    + ("" if state != "unknown" else " (codex 를 부르지 못해 확인 못 함)")))
        return out

    def guard(self, cfg=None):
        net = bool(opts(cfg).get("network"))
        return [
            ("셸 명령(rm·git push·배포·키체인·비밀 파일·서비스)", "같음",
             "PreToolUse 훅(gate.py)이 코드 모드(exec) 안의 명령에도 걸린다. 막으면 Codex 가 명령을 돌리지 않는다"),
            ("파일 쓰기(hooks/·장부·엔진 울타리)", "같음",
             "apply_patch 의 파일 자리를 본다. 'Delete File'(영구 삭제)은 rm 과 같은 규칙"),
            ("MCP 도구(보내기·답장·전달·삭제)", "같음", "도구 이름으로 막는다(Claude 와 같은 규칙)"),
            ("권한 잠금 거부(settings.json)", "약함",
             "Codex 에는 세션마다 줄 수 있는 같은 장치가 없다(규칙 파일은 사용자 설정 폴더에만). 같은 항목은 문지기가 막는다. "
             "hooks/permissions.json 의 allow·deny 는 Codex 에 쓰이지 않는다(additionalDirectories 만 쓰기 허용 폴더로 쓰임)"),
            ("하위 Agent 제한(push·승인 요청·알림 금지)", "약함",
             "Codex 훅 입력에 하위 Agent 표시가 있는지 확인 못 했다. 하위 Agent 도 주 Agent 규칙으로 본다"
             "(승인 요청은 그래도 대표 버튼이 있어야 실행)"),
            ("대화형 프로그램에 넣는 글(write_stdin)", "확인 못 함",
             "Codex 문서: 이미 띄운 명령에 넣는 글은 훅이 다시 보지 않는다. 문지기가 write_stdin 도구를 보도록 걸었지만 실제로 "
             "훅이 불리는지는 확인 못 했다"),
            ("샌드박스", "강함" if not net else "같음",
             "쓰기는 홈·임시 폴더(와 더한 폴더)만, .git·.codex·.agents 는 읽기 전용. "
             + ("네트워크 꺼짐: 셸로 보내기·배포·push 가 나가지 못한다" if not net else "네트워크 켜짐(Claude 와 같음)")),
            ("ChatGPT 앱(연결)·브라우저·컴퓨터 사용", "꺼 둠", "훅이 거는지 확인 못 해 데몬 세션에서 끈다(config codex.apps)"),
            ("문지기 신뢰", "다름",
             "데몬·jarvis agent open 세션은 --dangerously-bypass-hook-trust 로 늘 돈다(사용자 Codex 설정의 다른 훅도 검토 없이 돈다). "
             "그냥 연 Codex 에서는 플러그인 훅을 /hooks 에서 신뢰해야 돈다(그 전에는 문지기 없음)"),
            ("문지기 고장", "같음", "훅이 고장 나면 막지 않고 통과(둘 다 같은 설계)"),
        ]

    def doctor_hint(self):
        return "이 컴퓨터의 터미널에서 `jarvis agent status` 를 보고, Codex 에서 '$jarvis:doctor' 로 점검해 주세요"


def shlex_quote(s):
    import shlex
    return shlex.quote(s)
