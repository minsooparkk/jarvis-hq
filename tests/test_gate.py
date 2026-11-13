"""문지기 훅: 막을 것은 막고 통과시킬 것은 통과시킨다."""

import importlib.util
import json
import os
import subprocess
import sys

import pytest

from conftest import PLUGIN

GATE = PLUGIN / "hooks" / "gate.py"


@pytest.fixture
def gate(env):
    spec = importlib.util.spec_from_file_location("gate_under_test", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # HOME 을 바꾼 뒤 불러온다
    mod.TMP_OK = ("/tmp/", "/private/tmp/")  # 시험 임시 폴더(/private/var/folders)가 '지워도 되는 곳' 으로 보이지 않게
    cfg, paths = env

    def judge(tool="Bash", cwd=None, agent_id="", **inp):
        ev = {"tool_name": tool, "tool_input": inp, "cwd": str(cwd or paths.home)}
        if agent_id:
            ev["agent_id"] = agent_id
        r = mod.judge(ev)
        return r[0] if r else "allow"
    judge.paths = paths
    judge.mod = mod
    return judge


def bash(gate, command, **kw):
    return gate(command=command, **kw)


@pytest.mark.parametrize("cmd", [
    "rm -rf ~/Documents/x",
    "rm notes.md",
    "git push --force origin main",
    "git push origin +main",
    "git push origin :old",
    "sqlite3 .harness/ledger/executor.db 'delete from requests'",
    "launchctl bootout gui/501/com.jarvis-hq.jarvisd",
    "kill -9 1234",
    "killall python3",
    "pkill -f jhq.daemon",
    "wrangler deploy",
    "npx wrangler deploy",
    "vercel",
    "vercel --prod",
    "npm publish",
    "gh release create v1",
    "gh pr merge 3",
    "docker volume prune -f",
    "security find-generic-password -s x -w",
    "cat ~/.ssh/id_rsa",
    "cat .env",
    "head -3 config/.env.local",
    "jarvis secret set telegram",
    "jarvis exec resume",
    "jarvis exec daemon",
    "python3 -m jhq.daemon",
    "python3 -m jhq.extras.gmail send",
    "whisper-cli -m model.bin -f a.wav",
    "mv .harness/state/executor.pause /tmp/",
    "echo '{}' > hooks/gate.json",
    "tee .harness/ledger/outbox.db < /dev/null",
    "cp new.yaml hooks/targets.yaml",
    "sed -i '' 's/a/b/' hooks/targets.yaml",
    "python3 -c \"open('hooks/targets.yaml','w').write('x')\"",
])
def test_blocks_in_home(gate, cmd):
    assert bash(gate, cmd) == "deny", cmd


@pytest.mark.parametrize("cmd", [
    "rm /tmp/x.txt",
    "rm -rf .harness/work/old-task",
    "mv notes.md ~/.Trash/",
    "git status",
    "git commit -m 'x'",
    "sqlite3 -readonly .harness/ledger/executor.db 'select 1'",
    "launchctl list",
    "launchctl print gui/501/com.jarvis-hq.jarvisd",
    "kill -TERM 1234",
    "wrangler whoami",
    "vercel ls",
    "gh release list",
    "gh pr view 3",
    "docker ps",
    "jarvis secret list",
    "jarvis exec request --target hello --if-rejected x --결론 y",
    "jarvis exec pending",
    "jarvis stt a.wav",
    "which whisper-cli",
    "cat rules/02-승인.md",
    "ls -la",
    "python3 -m pytest tests -q",
    "printenv PATH",
])
def test_allows_in_home(gate, cmd):
    assert bash(gate, cmd) == "allow", cmd


def test_outside_home_only_own_fences(gate, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert bash(gate, "rm -rf build", cwd=other) == "allow"
    assert bash(gate, "git push --force", cwd=other) == "allow"
    assert bash(gate, "jarvis secret set telegram", cwd=other) == "deny"
    assert bash(gate, f"rm {gate.paths.home}/hooks/gate.json", cwd=other) == "deny"
    assert bash(gate, "security find-generic-password -s jarvis-hq.seal-key -w", cwd=other) == "deny"
    assert gate(tool="mcp__claude_ai_Gmail__send_message", cwd=other) == "allow"


def test_daemon_session_is_in_scope(gate, tmp_path, monkeypatch):
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("JARVIS_HQ_AGENT", "Jarvis")
    assert bash(gate, "rm -rf build", cwd=other) == "deny"


def test_subagent_cannot_request_or_notify(gate):
    assert bash(gate, "jarvis exec request --target hello --if-rejected x --결론 y", agent_id="a1") == "deny"
    assert bash(gate, "jarvis notify dm hi", agent_id="a1") == "deny"
    assert bash(gate, "jarvis mail request --to a@example.com", agent_id="a1") == "deny"
    assert bash(gate, "git push origin main", agent_id="a1") == "deny"
    assert bash(gate, "jarvis exec pending", agent_id="a1") == "allow"


def test_push_only_to_allowed_remote(gate, tmp_path):
    repo = gate.paths.home / ".harness" / "work" / "r"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/someone/repo.git"], check=True)
    assert bash(gate, "git push origin main", cwd=repo) == "deny"
    g = json.loads((gate.paths.home / "hooks" / "gate.json").read_text())
    g["push_ok"] = ["github.com/someone/"]
    (gate.paths.home / "hooks" / "gate.json").write_text(json.dumps(g))
    assert bash(gate, "git push origin main", cwd=repo) == "allow"
    assert bash(gate, "git push -f origin main", cwd=repo) == "deny"


def test_file_tools(gate):
    h = gate.paths.home
    assert gate(tool="Edit", file_path=str(h / "hooks" / "targets.yaml")) == "deny"
    assert gate(tool="Write", file_path=str(h / ".harness" / "ledger" / "x.json")) == "deny"
    assert gate(tool="Write", file_path=str(h / "rules" / "11-new.md")) == "allow"
    assert gate(tool="Read", file_path=str(h / ".env")) == "deny"
    assert gate(tool="Read", file_path=str(h / "hooks" / "targets.yaml")) == "allow"
    assert gate(tool="Read", file_path=os.path.expanduser("~/.ssh/config")) == "deny"


def test_mcp_tools(gate):
    assert gate(tool="mcp__claude_ai_Gmail__send_message") == "deny"
    assert gate(tool="mcp__claude_ai_Gmail__reply") == "deny"
    assert gate(tool="mcp__claude_ai_Microsoft_365__outlook_send_mail") == "deny"
    assert gate(tool="mcp__claude_ai_Slack__slack_send_message") == "deny"
    assert gate(tool="mcp__claude_ai_Gmail__create_draft") == "allow"
    assert gate(tool="mcp__claude_ai_Gmail__search_threads") == "allow"
    assert gate(tool="mcp__claude_ai_Microsoft_365__outlook_create_reply_draft") == "allow"
    assert gate(tool="mcp__claude_ai_Microsoft_365__outlook_send_draft") == "deny"
    assert gate(tool="mcp__claude_ai_Gmail__untrash_thread") == "allow"


def test_unparseable_risky_command(gate):
    assert bash(gate, "rm 'unclosed") == "deny"
    assert bash(gate, "echo 'unclosed") == "allow"


def test_hook_protocol_via_stdin(env):
    _cfg, paths = env
    ev = {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}, "cwd": str(paths.home)}
    r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(ev), capture_output=True, text=True, env=os.environ.copy())
    out = json.loads(r.stdout)
    assert r.returncode == 0
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "push" in out["hookSpecificOutput"]["permissionDecisionReason"]
    ev["tool_input"]["command"] = "ls"
    r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(ev), capture_output=True, text=True, env=os.environ.copy())
    assert r.stdout.strip() == "" and r.returncode == 0
    r = subprocess.run([sys.executable, str(GATE)], input="not json", capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_system_python_runs_gate(env):
    """맥 기본 python3 로도 돈다(플러그인 훅은 이것으로 돈다)."""
    _cfg, paths = env
    ev = {"tool_name": "Bash", "tool_input": {"command": "git push --force"}, "cwd": str(paths.home)}
    r = subprocess.run(["/usr/bin/python3", str(GATE)], input=json.dumps(ev), capture_output=True, text=True, env=os.environ.copy())
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


# ---------- 윈도 명령·PowerShell (규칙은 OS 와 상관없이 맥에서도 시험된다) ----------

@pytest.mark.parametrize("cmd", [
    "schtasks /Delete /TN com.jarvis-hq.jarvisd /F",
    "schtasks /End /TN com.jarvis-hq.executor",
    "taskkill /F /PID 1234",
    "taskkill /IM python.exe",
    "cmdkey /delete:jarvis-hq.seal-key",
    "powershell -Command \"Remove-Item -Recurse C:/x\"",
    "powershell.exe -Command \"Stop-Process -Id 4\"",
    "python -c \"import keyring; keyring.get_password('jarvis-hq.seal-key', 'a')\"",
])
def test_blocks_windows_commands_in_home(gate, cmd):
    assert bash(gate, cmd) == "deny", cmd


@pytest.mark.parametrize("cmd", ["schtasks /Query /TN com.jarvis-hq.jarvisd", "taskkill /PID 1234", "cmdkey /list"])
def test_allows_windows_reads(gate, cmd):
    assert bash(gate, cmd) == "allow", cmd


def test_powershell_tool(gate, tmp_path):
    ps = lambda c, **kw: gate(tool="PowerShell", command=c, **kw)  # noqa: E731
    assert ps("Remove-Item notes.md") == "deny"
    assert ps("Get-ChildItem") == "allow"
    assert ps("git push --force origin main") == "deny"  # bash 와 같은 규칙
    assert ps("Set-Content hooks/gate.json '{}'") == "deny"
    assert ps("jarvis secret set telegram") == "deny"
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert ps("Remove-Item build", cwd=other) == "allow"  # Jarvis 밖 세션은 울타리만
    assert ps(f"Set-Content {gate.paths.home}/hooks/gate.json x", cwd=other) == "deny"


def test_windows_paths(gate):
    m = gate.mod
    try:
        m.WIN = True
        assert m.cmdname("C:\\Program Files\\Git\\usr\\bin\\RM.EXE") == "rm" and m.cmdname("jarvis.cmd") == "jarvis"
        assert m.from_msys("/c/Users/홍길동/jarvis") == "C:/Users/홍길동/jarvis"
        assert m.norm("C:\\Users\\Hong\\Jarvis") == "c:/users/hong/jarvis"
    finally:
        m.WIN = False
    assert m.cmdname("/usr/bin/rm") == "rm" and m.norm("/Users/A") == "/Users/A"


def test_hooks_json_runs_through_sh_launcher(env):
    """플러그인 훅 명령(sh run.sh …)을 맥 sh 로 그대로 돌린다(윈도는 Git Bash 가 같은 줄을 돌린다)."""
    _cfg, paths = env
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    cmd = hooks["PreToolUse"][0]["hooks"][0]["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    assert "PowerShell" in hooks["PreToolUse"][0]["matcher"]
    ev = {"tool_name": "Bash", "tool_input": {"command": "jarvis secret set telegram"}, "cwd": str(paths.home)}
    r = subprocess.run(["/bin/sh", "-c", cmd], input=json.dumps(ev), capture_output=True, text=True, env=os.environ.copy())
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    cmd = hooks["SessionStart"][0]["hooks"][0]["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    r = subprocess.run(["/bin/sh", "-c", cmd], input=json.dumps({"cwd": str(paths.home)}), capture_output=True, text=True,
                       env=os.environ.copy())
    assert "additionalContext" in r.stdout


def test_gate_reads_utf8_stdin_bytes(env):
    _cfg, paths = env
    ev = {"tool_name": "Bash", "tool_input": {"command": "cat ~/.ssh/한글파일"}, "cwd": str(paths.home)}
    r = subprocess.run([sys.executable, str(GATE)], input=json.dumps(ev, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, env={**os.environ, "PYTHONIOENCODING": "latin-1"})
    assert r.stdout, r.stderr.decode("utf-8", "replace")
    out = json.loads(r.stdout.decode("utf-8"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny" and "한글파일" in out["hookSpecificOutput"]["permissionDecisionReason"]
