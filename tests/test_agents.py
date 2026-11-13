"""에이전트 층(jhq.agents): Claude Code 는 예전 그대로, Codex 는 명령·출력 읽기·홈 파일·문지기 연결·설치·명령.
실제 codex 는 부르지 않는다(가짜 codex 스크립트·가짜 실행기). 실제로 돌려 본 것은 docs/codex-확인할-것.md."""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from conftest import PLUGIN, seal_key
from jhq import agents, config, daemon
from jhq.agents import codex as cx

def fake_codex(tmp_path, body):
    p = tmp_path / "bin" / "codex"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"#!{sys.executable}\nimport json, os, sys, time\n" + textwrap.dedent(body))
    p.chmod(0o755)
    return str(p)


def codex_cfg(cfg, path, **kw):
    c = dict(cfg)
    c["agent"] = "codex"
    c["codex"] = dict(cfg.get("codex") or {}, path=path, **kw)
    return c


def opt(cmd, key):
    """명령 줄에서 -c key=값 의 값(TOML 글)."""
    for i, a in enumerate(cmd):
        if a == "-c" and cmd[i + 1].startswith(key + "="):
            return cmd[i + 1][len(key) + 1:]
    return None


# ---------- 고르기 ----------

def test_kind_default_and_unknown():
    assert agents.kind({}) == "claude" and agents.kind({"agent": "Codex"}) == "codex"
    with pytest.raises(agents.UnknownAgent):
        agents.kind({"agent": "gemini"})
    assert agents.get("claude").home_file == "CLAUDE.md" and agents.get({"agent": "codex"}).home_file == "AGENTS.md"


def test_config_default_is_claude(env):
    cfg, _paths = env
    assert cfg["agent"] == "claude" and cfg["codex"]["network"] is False


def test_toml_values():
    assert cx.toml("따옴표\"와 줄\n") == '"따옴표\\"와 줄\\n"'
    assert cx.toml([{"matcher": "a|b", "hooks": [{"timeout": 20, "x": True}]}]) == \
        '[{matcher = "a|b", hooks = [{timeout = 20, x = true}]}]'


# ---------- Codex 명령 ----------

def test_codex_command_has_fence(env, tmp_path):
    cfg, paths = env
    cfg = codex_cfg(cfg, fake_codex(tmp_path, ""))
    a = agents.get("codex")
    cmd = a.command(cfg, config.plat(), paths, "sess-1", False, "메신저 말투")
    assert cmd[1:3] == ["exec", "--json"] and cmd[-1] == "-"  # 질문은 표준입력
    assert "--dangerously-bypass-hook-trust" in cmd and "resume" not in cmd
    assert opt(cmd, "sandbox_mode") == '"workspace-write"' and opt(cmd, "approval_policy") == '"never"'
    assert opt(cmd, "sandbox_workspace_write.network_access") == "false" and opt(cmd, "features.hooks") == "true"
    assert opt(cmd, "features.apps") == "false" and opt(cmd, "features.computer_use") == "false"
    hooks = opt(cmd, "hooks.PreToolUse")
    assert "apply_patch" in hooks and "write_stdin" in hooks and "gate.py" in hooks
    assert opt(cmd, "hooks.SessionStart") is None  # 세션 시작 맥락은 플러그인 훅으로만(Claude 와 같음)
    assert opt(cmd, "mcp_servers.korea-tax-law.url").startswith('"https://')
    assert opt(cmd, "developer_instructions") == '"메신저 말투"'
    again = a.command(cfg, config.plat(), paths, "T-9", True, "")
    assert again[1:3] == ["exec", "resume"] and again[-2:] == ["T-9", "-"] and opt(again, "developer_instructions") is None


def test_codex_network_model_and_roots(env, tmp_path):
    cfg, paths = env
    extra = tmp_path / "repos"
    paths.permissions.write_text(json.dumps({"additionalDirectories": [str(extra)]}), encoding="utf-8")
    cfg = codex_cfg(cfg, fake_codex(tmp_path, ""), network=True, model="gpt-x", apps=True)
    cmd = agents.get("codex").command(cfg, config.plat(), paths, "s", False)
    assert opt(cmd, "sandbox_workspace_write.network_access") == "true" and opt(cmd, "model") == '"gpt-x"'
    assert json.loads(opt(cmd, "sandbox_workspace_write.writable_roots")) == [str(extra)]
    assert opt(cmd, "features.apps") is None


STREAM = """
assert sys.argv[1:3] == ["exec", "--json"] or sys.argv[1:3] == ["exec", "resume"], sys.argv
prompt = sys.stdin.read()
pr = lambda o: print(json.dumps(o, ensure_ascii=False), flush=True)
resume = sys.argv[2] == "resume"
pr({"type": "thread.started", "thread_id": sys.argv[-2] if resume else "T-1"})
pr({"type": "item.completed", "item": {"id": "i0", "type": "error", "message": "`--dangerously-bypass-hook-trust` is enabled."}})
pr({"type": "turn.started"})
pr({"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "메일함부터 볼게요."}})
pr({"type": "item.started", "item": {"id": "i2", "type": "command_execution", "command": "ls", "status": "in_progress"}})
pr({"type": "item.completed", "item": {"id": "i2", "type": "command_execution", "command": "ls", "exit_code": 0}})
pr({"type": "item.started", "item": {"id": "i3", "type": "mcp_tool_call", "server": "korea-tax-law", "tool": "search_law"}})
leak = os.environ.get("TELEGRAM_BOT_TOKEN")
first = os.environ["PATH"].split(os.pathsep)
pr({"type": "item.completed", "item": {"id": "i4", "type": "agent_message",
    "text": "답: " + prompt + " leak=" + str(leak) + " agent=" + os.environ["JARVIS_HQ_AGENT"]
            + " path_ok=" + str(os.path.dirname(sys.argv[0]) in first)}})
pr({"type": "turn.completed", "usage": {}})
"""


def test_codex_run_parses_events(env, tmp_path, monkeypatch):
    cfg, paths = env
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "should-not-leak")
    cfg = codex_cfg(cfg, fake_codex(tmp_path, STREAM))
    said, tools = [], []
    out = agents.get("codex").run(cfg, paths, "-로 시작하는 질문", "placeholder", on_text=said.append, on_tool=tools.append)
    assert out == "답: -로 시작하는 질문 leak=None agent=Jarvis path_ok=True"
    assert out.session == "T-1" and said == ["메일함부터 볼게요."] and tools == ["Bash", "mcp__korea-tax-law__search_law"]
    again = agents.get("codex").run(cfg, paths, "또", "T-1", resume=True)
    assert again.session == "T-1" and again.startswith("답: 또")


def test_codex_run_failures(env, tmp_path, monkeypatch):
    cfg, paths = env
    failed = codex_cfg(cfg, fake_codex(tmp_path, """
        sys.stdin.read()
        print(json.dumps({"type": "thread.started", "thread_id": "T"}), flush=True)
        print(json.dumps({"type": "error", "message": "Reconnecting... 1/5"}), flush=True)
        print(json.dumps({"type": "turn.failed", "error": {"message": "401 Unauthorized"}}), flush=True)
    """))
    with pytest.raises(RuntimeError, match="401"):
        agents.get("codex").run(failed, paths, "x", "s")
    monkeypatch.setattr(daemon, "STALL", 1)
    slow = codex_cfg(cfg, fake_codex(tmp_path, "time.sleep(10)\n"))
    with pytest.raises(daemon.StallError):
        daemon.run_agent(slow, paths, "x", "s")


def test_claude_is_still_default_runner(env, tmp_path):
    cfg, paths = env
    p = tmp_path / "fake-claude"
    p.write_text(f"#!{sys.executable}\nimport json, sys\nassert '--session-id' in sys.argv\n"
                 "print(json.dumps({'type': 'result', 'is_error': False, 'result': 'claude 답'}))\n")
    p.chmod(0o755)
    out = daemon.run_agent(dict(cfg, claude=str(p)), paths, "x", "sess-9")
    assert out == "claude 답" and out.session == "sess-9"


# ---------- 데몬: Codex 대화 id ----------

def test_daemon_binds_codex_thread_id(env):
    from test_daemon import FakeMessenger, dm
    cfg, paths = env
    calls = []

    def runner(cfg, paths, prompt, session, resume=False, context="", **kw):
        calls.append((session, resume))
        return agents.Reply(f"답{len(calls)}", session if resume else f"T-{len(calls)}")

    d = daemon.Daemon(codex_cfg(cfg, "codex"), paths, FakeMessenger(), seal_key(cfg), runner=runner)
    d.handle_message(dm("안녕"))
    d.handle_message(dm("또", msg=2))
    assert calls[0][1] is False and calls[1] == ("T-1", True)
    st = json.loads(paths.daemon_state.read_text())
    key = next(k for k in st["sessions"])
    assert key.startswith("codex/dm-") and st["sessions"][key] == "T-1"
    d.handle_message(dm("/new", msg=3))
    assert not json.loads(paths.daemon_state.read_text())["sessions"]


def test_daemon_merge_uses_bound_id(env):
    """답을 만드는 동안 온 말을 합칠 때도 Codex 가 정한 id 로 이어 간다."""
    from test_daemon import FakeMessenger, dm
    cfg, paths = env
    calls = []

    def runner(cfg, paths, prompt, session, resume=False, context="", **kw):
        calls.append((session, resume))
        return agents.Reply("답", session if resume else "T-7")

    d = daemon.Daemon(codex_cfg(cfg, "codex"), paths, FakeMessenger(), seal_key(cfg), runner=runner)
    orig, n = d.talk_more, {"k": 0}

    def more(key, done=False):
        if not done and n["k"] == 0:
            n["k"] = 1
            return ["덧붙인 말"]
        return orig(key, done)
    d.talk_more = more
    d.handle_message(dm("처음"))
    assert calls[0][1] is False and calls[1] == ("T-7", True)


# ---------- 홈: AGENTS.md ----------

def test_agents_md_from_claude_md(env):
    cfg, paths = env
    home = paths.home
    (home / "rules").mkdir()
    (home / "rules" / "01-a.md").write_text("# 규칙 하나\n- 짧게\n", encoding="utf-8")
    (home / "CLAUDE.md").write_text("# 비서\n\n@rules/01-a.md\n@없는파일.md\n\n- 끝\n", encoding="utf-8")
    assert cx.sync_agents_md(paths) == "만듦"
    text = (home / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith(cx.MARKER) and "# 규칙 하나" in text and "@rules/" not in text and "없는파일.md" in text
    assert cx.sync_agents_md(paths) == "같음"
    (home / "rules" / "01-a.md").write_text("# 규칙 하나 고침\n", encoding="utf-8")
    assert cx.sync_agents_md(paths) == "새로 씀" and "고침" in (home / "AGENTS.md").read_text(encoding="utf-8")
    (home / "AGENTS.md").write_text("손으로 쓴 것\n", encoding="utf-8")
    r = cx.sync_agents_md(paths)
    assert r.startswith("새로 씀(옛 AGENTS.md") and list((paths.state / "backup").rglob("AGENTS.md"))


def test_template_agents_md_fits_and_has_rules(env):
    cfg, paths = env
    import shutil
    for f in ("CLAUDE.md", "RULES.md"):
        shutil.copy(PLUGIN / "template" / f, paths.home / f)
    shutil.copytree(PLUGIN / "template" / "rules", paths.home / "rules")
    text = cx.render_agents_md(paths.home)
    assert "불러올 파일이 없음" not in text and "@rules/" not in text and len(text.encode()) < 32 * 1024


def test_prepare_home_links_skills(env):
    cfg, paths = env
    (paths.home / "CLAUDE.md").write_text("# x\n", encoding="utf-8")
    made = agents.get("codex").prepare_home(paths, cfg)
    assert os.readlink(paths.home / ".agents" / "skills") == "../skills" and any("AGENTS.md" in m for m in made)
    assert agents.get("codex").prepare_home(paths, cfg) == []


# ---------- 점검·플러그인 ----------

class Run:
    def __init__(self, out="", code=0):
        self.calls, self.out, self.code = [], out, code

    def __call__(self, argv):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, self.code, stdout=self.out, stderr="")


def test_plugin_state(env, tmp_path):
    cfg, _paths = env
    cfg = codex_cfg(cfg, fake_codex(tmp_path, ""))
    ok = {"installed": [{"pluginId": "jarvis@jarvis-hq", "installed": True, "enabled": True}]}
    run = Run(json.dumps(ok))
    assert cx.Codex(run=run).plugin_state(cfg, config.plat()) == "installed" and run.calls[0][-3:] == ["plugin", "list", "--json"]
    assert cx.Codex(run=Run(json.dumps({"installed": []}))).plugin_state(cfg, config.plat()) == "missing"
    assert cx.Codex(run=Run("not json")).plugin_state(cfg, config.plat()) == "unknown"
    assert cx.Codex().plugin_plan("minsooparkk/jarvis-hq")[-1] == ["plugin", "add", "jarvis@jarvis-hq"]


def test_guard_table_names_weak_spots():
    rows = {i: lv for i, lv, _n in agents.get("codex").guard({"codex": {"network": False}})}
    assert rows["샌드박스"] == "강함" and "약함" in rows.values() and "확인 못 함" in rows.values()
    assert agents.get("codex").guard({"codex": {"network": True}})[6][1] == "같음"


def test_windows_codex_cmd_resolves(tmp_path):
    from test_platform import winplat
    w = winplat(tmp_path)
    npm = tmp_path / "npm"
    js = npm / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    js.parent.mkdir(parents=True)
    js.write_text("")
    (npm / "node.exe").write_text("")
    cfg = {"codex": {"path": str(npm / "codex.cmd")}}
    assert agents.get("codex").argv(cfg, w) == [str(npm / "node.exe"), str(js)]
    js.unlink()
    exe = npm / "node_modules" / "@openai" / "codex" / "node_modules" / "@openai" / "codex-win32-x64" / "vendor" / "x" / "bin"
    exe.mkdir(parents=True)
    (exe / "codex.exe").write_text("")
    assert agents.get("codex").argv(cfg, w) == [str(exe / "codex.exe")]
    assert agents.get("codex").hook_command(w, "gate.py").startswith('"')


# ---------- 명령 jarvis agent ----------

def test_cli_agent_set_status_mcp(env, tmp_path, monkeypatch, capsys):
    from jhq import cli
    cfg, paths = env
    monkeypatch.setenv("JARVIS_HQ_NO_SERVICES", "1")
    (paths.home / "CLAUDE.md").write_text("# 비서\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path / "빈 폴더"))
    assert cli.main(["agent", "set", "codex"]) == 2  # codex 를 못 찾으면 바꾸지 않음
    assert json.loads(config.config_path().read_text(encoding="utf-8")).get("agent", "claude") == "claude"
    path = fake_codex(tmp_path, """
        if sys.argv[1:] == ["--version"]:
            print("codex-cli 9.9.9")
        elif sys.argv[1:3] == ["plugin", "list"]:
            print(json.dumps({"installed": [{"pluginId": "jarvis@jarvis-hq", "installed": True}]}))
    """)
    capsys.readouterr()
    assert cli.main(["agent", "set", "codex", "--path", path, "--network", "off"]) == 0
    out = capsys.readouterr().out
    assert "Codex" in out and "다시 켜지 않았습니다" in out
    saved = json.loads(config.config_path().read_text(encoding="utf-8"))
    assert saved["agent"] == "codex" and saved["codex"]["path"] == path and (paths.home / "AGENTS.md").exists()
    assert cli.main(["agent", "status", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["agent"] == "codex" and rep["version"] == "codex-cli 9.9.9" and rep["network"] is False
    assert all(c["ok"] for c in rep["checks"]), rep["checks"]
    assert any(g["level"] == "약함" for g in rep["guard"])
    assert cli.main(["agent", "mcp"]) == 0 and "codex mcp add korea-tax-law --url https://" in capsys.readouterr().out
    assert cli.main(["agent", "set", "claude", "--no-restart"]) == 0
    assert json.loads(config.config_path().read_text(encoding="utf-8"))["agent"] == "claude"
    assert cli.main(["agent", "open"]) == 2  # Claude 일 때는 안내만
