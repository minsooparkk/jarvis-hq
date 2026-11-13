"""OS 층: 맥 구현은 예전과 같은 명령·파일을, 윈도 구현은 가짜 실행기·가짜 금고로 만드는 명령·XML·바로가기를 본다.
(이 기계는 맥이라 윈도에서 실제로 돌려 보지 못한다. 실제 기기 점검표: docs/윈도우-확인할-것.md)"""

import importlib.util
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from conftest import PLUGIN
from jhq import platform as osplat
from jhq.platform import ServiceSpec, Unsupported
from jhq.platform import windows as win
from jhq.platform import winlaunch


class Runner:
    """subprocess.run 대신. 부른 명령을 모으고 정해 둔 답을 준다."""

    def __init__(self, answers=None):
        self.calls, self.kw, self.answers = [], [], answers or {}

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        self.kw.append(kw)
        for key, (code, out) in self.answers.items():
            if key(argv):
                return subprocess.CompletedProcess(argv, code, stdout=out, stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class Vault:
    def __init__(self):
        self.d = {}

    def read(self, target):
        return self.d.get(target)

    def write(self, target, user, blob):
        self.d[target] = (user, blob)

    def delete(self, target):
        return self.d.pop(target, None) is not None


def winplat(tmp_path, run=None, **env):
    home = tmp_path / "사용자 홍길동"
    home.mkdir(exist_ok=True)
    environ = {"USERNAME": "홍길동", "USERDOMAIN": "DESKTOP-1", "PATH": ""}
    environ.update(env)
    return osplat.get("windows", run=run or Runner(), home=home, environ=environ, vault=Vault())


def spec(tmp_path, name="jarvisd", keepalive=True):
    e = tmp_path / "사용자 홍길동" / ".jarvis-hq"
    return ServiceSpec(name, f"com.jarvis-hq.{name}", e / "venv" / "Scripts" / "pythonw.exe", "jhq.daemon", [],
                       workdir=tmp_path / "사용자 홍길동" / "jarvis", env={"JARVIS_HQ_DIR": str(e), "LANG": "ko_KR.UTF-8"},
                       log=tmp_path / "logs" / f"{name}.log", keepalive=keepalive, interval=None if keepalive else 300,
                       engine=e)


# ---------- 고르기 ----------

def test_kind_and_unsupported(tmp_path):
    assert osplat.kind("darwin") == "mac" and osplat.kind("win32") == "windows" and osplat.kind("linux") == "unsupported"
    lin = osplat.get("unsupported", home=tmp_path)
    assert not lin.supported
    with pytest.raises(Unsupported, match="지원하지 않습니다"):
        lin.secret_get("a", "b")
    with pytest.raises(Unsupported):
        lin.service_states(["x"])


def test_engine_code_does_not_look_at_sys_platform():
    """OS 를 보는 것은 jhq/platform 과 혼자 도는 훅 둘뿐."""
    engine = PLUGIN / "engine" / "jhq"
    for f in engine.rglob("*.py"):
        if "platform" in f.relative_to(engine).parts:
            continue
        text = f.read_text(encoding="utf-8")
        for word in ("sys.platform", "os.name", '"launchctl"', '"schtasks"', '"security"', "getuid", "import fcntl"):
            assert word not in text, (f, word)
    text = (PLUGIN / "scripts" / "install.py").read_text(encoding="utf-8")
    for word in ("sys.platform", '"launchctl"', '"schtasks"', '"security"', "getuid", "plistlib"):
        assert word not in text, word


# ---------- 맥(예전과 같게) ----------

def test_mac_plist_and_plan_unchanged(tmp_path):
    run = Runner({lambda a: a[:2] == ["launchctl", "print"]: (113, "")})
    m = osplat.get("mac", run=run, home=tmp_path, uid=501)
    s = ServiceSpec("jarvisd", "com.jarvis-hq.jarvisd", "/e/venv/bin/python", "jhq.daemon", [], workdir="/h/jarvis",
                    env={"JARVIS_HQ_DIR": "/e"}, log="/h/l.log", keepalive=True, engine="/e")
    [(path, data)] = m.service_files(s)
    import plistlib
    d = plistlib.loads(data)
    assert path == tmp_path / "Library" / "LaunchAgents" / "com.jarvis-hq.jarvisd.plist"
    assert d["ProgramArguments"] == ["/e/venv/bin/python", "-u", "-m", "jhq.daemon"] and d["KeepAlive"] is True
    assert not m.service_loaded("com.jarvis-hq.jarvisd")
    plan = m.service_plan(s, changed=False, loaded=False, restart=False)
    assert plan[0] == ["launchctl", "bootout", "gui/501/com.jarvis-hq.jarvisd"] and plan[1][1] == "bootstrap"
    assert m.service_plan(s, changed=False, loaded=True, restart=True) == [["launchctl", "kickstart", "-k",
                                                                           "gui/501/com.jarvis-hq.jarvisd"]]
    assert m.hook_entry("/e/hooks/gate.py", "/x/python")["command"] == "/usr/bin/python3 '/e/hooks/gate.py'"


def test_mac_states_and_keychain_commands(tmp_path):
    listing = "PID\tStatus\tLabel\n111\t0\tcom.jarvis-hq.jarvisd\n-\t1\tcom.jarvis-hq.executor\n"
    run = Runner({lambda a: a[:2] == ["launchctl", "list"]: (0, listing)})
    m = osplat.get("mac", run=run, home=tmp_path, uid=501)
    st = m.service_states(["com.jarvis-hq.jarvisd", "com.jarvis-hq.executor", "com.jarvis-hq.watchdog"])
    assert st == {"com.jarvis-hq.jarvisd": ("running", "111"), "com.jarvis-hq.executor": ("stopped", None),
                  "com.jarvis-hq.watchdog": ("missing", None)}
    m.secret_put("jarvis-hq.seal-key", "jarvis-hq", "값")
    assert run.calls[-1] == ["security", "-i"] and "값" not in " ".join(run.calls[-1])  # 값은 표준입력으로만
    assert "값" in run.kw[-1]["input"]


# ---------- 윈도: 서비스 ----------

def test_windows_task_xml(tmp_path):
    w = winplat(tmp_path)
    s = spec(tmp_path)
    files = dict(w.service_files(s))
    xml_path, json_path = w.files_for(s.label, s.engine)
    raw = files[xml_path]
    assert raw[:2] in (b"\xff\xfe", b"\xfe\xff")  # UTF-16(BOM)
    root = ET.fromstring(raw.decode("utf-16").replace('encoding="UTF-16"', ""))
    ns = {"t": win.TASK_NS}
    assert root.find("t:Triggers/t:LogonTrigger/t:UserId", ns).text == "DESKTOP-1\\홍길동"
    assert root.find("t:Principals/t:Principal/t:LogonType", ns).text == "InteractiveToken"
    assert root.find("t:Principals/t:Principal/t:RunLevel", ns).text == "LeastPrivilege"  # 관리자 권한 없이
    assert root.find("t:Settings/t:ExecutionTimeLimit", ns).text == "PT0S"  # 72시간 뒤에 죽지 않게
    assert root.find("t:Settings/t:RestartOnFailure/t:Interval", ns).text == "PT1M"
    assert root.find("t:Settings/t:DisallowStartIfOnBatteries", ns).text == "false"
    ex = root.find("t:Actions/t:Exec", ns)
    assert ex.find("t:Command", ns).text.endswith("pythonw.exe")  # 콘솔 창이 뜨지 않게
    args = ex.find("t:Arguments", ns).text
    assert args.startswith('"') and "winlaunch.py" in args and str(json_path) in args  # 공백·한글 경로를 따옴표로
    launch = json.loads(files[json_path].decode("utf-8"))
    assert launch["module"] == "jhq.daemon" and launch["env"]["LANG"] == "ko_KR.UTF-8" and "PATH" not in launch["env"]


def test_windows_watchdog_task_repeats(tmp_path):
    w = winplat(tmp_path)
    s = spec(tmp_path, "watchdog", keepalive=False)
    raw = dict(w.service_files(s))[w.files_for(s.label, s.engine)[0]]
    root = ET.fromstring(raw.decode("utf-16").replace('encoding="UTF-16"', ""))
    ns = {"t": win.TASK_NS}
    assert root.find("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval", ns).text == "PT5M"
    assert root.find("t:Settings/t:RestartOnFailure", ns) is None
    assert w.service_plan(s, changed=True, loaded=False, restart=False) == [
        ["schtasks", "/Create", "/TN", "com.jarvis-hq.watchdog", "/XML", str(w.files_for(s.label, s.engine)[0]), "/F"]]


def test_windows_service_plan_and_apply(tmp_path):
    run = Runner({lambda a: a[:2] == ["schtasks", "/End"]: (1, "")})
    w = winplat(tmp_path, run=run)
    s = spec(tmp_path)
    assert w.service_plan(s, changed=False, loaded=True, restart=False) == []
    plan = w.service_plan(s, changed=True, loaded=False, restart=False)
    assert [a[1] for a in plan] == ["/Create", "/End", "/Run"]
    assert w.apply(plan) == []  # /End 실패(안 돌던 작업)는 괜찮다
    assert all(kw.get("creationflags") == win.CREATE_NO_WINDOW for kw in run.kw)
    assert w.service_remove_plan(s.label) == [["schtasks", "/End", "/TN", s.label], ["schtasks", "/Delete", "/TN", s.label, "/F"]]


def test_windows_service_states_via_powershell(tmp_path):
    out = "com.jarvis-hq.jarvisd\tRunning\r\ncom.jarvis-hq.executor\tReady\r\ncom.jarvis-hq.watchdog\tmissing\r\n"
    run = Runner({lambda a: a[0] == "powershell.exe": (0, out)})
    w = winplat(tmp_path, run=run)
    st = w.service_states(["com.jarvis-hq.jarvisd", "com.jarvis-hq.executor", "com.jarvis-hq.watchdog", "x"])
    assert st == {"com.jarvis-hq.jarvisd": ("running", None), "com.jarvis-hq.executor": ("stopped", None),
                  "com.jarvis-hq.watchdog": ("missing", None), "x": ("unknown", None)}
    argv = run.calls[0]
    assert argv[:3] == ["powershell.exe", "-NoProfile", "-NonInteractive"] and "-EncodedCommand" in argv
    import base64
    script = base64.b64decode(argv[-1]).decode("utf-16-le")
    assert "Get-ScheduledTask" in script and "'com.jarvis-hq.jarvisd'" in script
    ok, _ = w.service_restart("com.jarvis-hq.jarvisd")
    assert ok and run.calls[-2][:2] == ["schtasks", "/End"] and run.calls[-1][:2] == ["schtasks", "/Run"]


def test_winlaunch_prepares_env(tmp_path):
    env = {"PATH": "C:\\Windows", "PYTHONPATH": ""}
    winlaunch.prepare({"env": {"JARVIS_HQ_DIR": "C:\\e"}, "pythonpath": "C:\\e\\engine", "path_prepend": ["C:\\b"]}, env)
    assert env["JARVIS_HQ_DIR"] == "C:\\e" and env["PYTHONUTF8"] == "1" and env["PYTHONPATH"] == "C:\\e\\engine"
    assert env["PATH"].startswith("C:\\b")


def test_winlaunch_runs_module_with_log(tmp_path):
    """맥 파이썬으로 입구 스크립트를 실제로 돌려 본다(모듈 실행·로그 돌리기·작업 폴더)."""
    pkg = tmp_path / "eng" / "fakepkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "hello.py").write_text("import os, sys\nprint('안녕', sys.argv[1:], os.environ['X'], os.getcwd())\n", encoding="utf-8")
    log = tmp_path / "logs" / "a.log"
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps({"module": "fakepkg.hello", "args": ["a"], "env": {"X": "값"}, "log": str(log),
                              "cwd": str(tmp_path), "pythonpath": str(tmp_path / "eng")}, ensure_ascii=False), encoding="utf-8")
    script = PLUGIN / "engine" / "jhq" / "platform" / "winlaunch.py"
    subprocess.run([sys.executable, str(script), str(sp)], check=True)
    text = log.read_text(encoding="utf-8")
    assert "안녕 ['a'] 값" in text and str(tmp_path) in text


# ---------- 윈도: 금고·바로가기·셸·claude ----------

def test_windows_vault(tmp_path):
    w = winplat(tmp_path)
    assert w.secret_get("jarvis-hq.x", "jarvis-hq") is None and not w.secret_has("jarvis-hq.x", "jarvis-hq")
    w.secret_put("jarvis-hq.x", "jarvis-hq", "토큰값")
    assert w.vault.d["jarvis-hq.x"] == ("jarvis-hq", "토큰값".encode("utf-8"))
    assert w.secret_get("jarvis-hq.x", "jarvis-hq") == "토큰값"
    with pytest.raises(RuntimeError, match="너무 깁니다"):
        w.secret_put("jarvis-hq.y", "jarvis-hq", "a" * 3000)
    assert w.secret_delete("jarvis-hq.x", "jarvis-hq") and not w.secret_delete("jarvis-hq.x", "jarvis-hq")


def test_windows_cli_wrappers(tmp_path):
    w = winplat(tmp_path)
    e = w.home / ".jarvis-hq"
    rep = {}
    cli = w.install_cli(e, e / "venv" / "Scripts" / "python.exe", rep)
    assert cli == e / "bin" / "jarvis.cmd"
    cmd = (e / "bin" / "jarvis.cmd").read_bytes().decode("utf-8")
    assert cmd.isascii() and "%JARVIS_HQ_DIR%\\venv\\Scripts\\python.exe" in cmd and "\r\n" in cmd  # 한글 경로를 적지 않음
    sh = (e / "bin" / "jarvis").read_text(encoding="utf-8")
    assert sh.startswith("#!/bin/sh") and '"$@"' in sh and "\\" not in sh.split("\n", 2)[2]  # Git Bash 용, / 경로
    shim = (w.user_bin() / "jarvis.cmd").read_bytes().decode("utf-8")
    assert "%USERPROFILE%\\.jarvis-hq\\bin\\jarvis.cmd" in shim and shim.isascii()
    (w.user_bin() / "jarvis").write_text("남의 파일", encoding="utf-8")
    rep = {}
    w.install_cli(e, e / "venv" / "Scripts" / "python.exe", rep)
    assert (w.user_bin() / "jarvis").read_text(encoding="utf-8") == "남의 파일" and rep["warnings"]
    rep = {}
    w.remove_cli(e, rep)
    assert not (w.user_bin() / "jarvis.cmd").exists() and (w.user_bin() / "jarvis").exists()


def test_windows_junction_command(tmp_path):
    run = Runner()
    w = winplat(tmp_path, run=run)
    link = tmp_path / "홈 폴더" / ".claude" / "skills"
    made = w.link_dir(link, "../skills")
    assert run.calls[-1][:4] == ["cmd", "/c", "mklink", "/J"] and run.calls[-1][4] == str(link)
    assert run.calls[-1][5] == str(tmp_path / "홈 폴더" / "skills") and "정션" in made


def test_windows_git_bash(tmp_path):
    pf = tmp_path / "Program Files"
    bash = pf / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("")
    assert winplat(tmp_path, ProgramFiles=str(pf)).bash() == str(bash)
    wsl = tmp_path / "System32" / "bash.exe"
    assert winplat(tmp_path, CLAUDE_CODE_GIT_BASH_PATH=str(bash)).bash() == str(bash)
    with pytest.raises(Unsupported, match="Git for Windows"):
        winplat(tmp_path, CLAUDE_CODE_GIT_BASH_PATH=str(wsl)).bash()


def test_windows_claude_argv(tmp_path):
    w = winplat(tmp_path)
    assert w.claude_argv("C:/Users/x/.local/bin/claude.exe") == ["C:/Users/x/.local/bin/claude.exe"]
    npm = tmp_path / "npm"
    cli = npm / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    (npm / "node.exe").write_text("")
    assert w.claude_argv(str(npm / "claude.cmd")) == [str(npm / "node.exe"), str(cli)]  # cmd.exe 를 거치지 않음
    cli.unlink()
    with pytest.raises(Unsupported):
        w.claude_argv(str(npm / "claude.cmd"))
    assert w.prompt_on_stdin


def test_windows_misc(tmp_path):
    run = Runner({lambda a: a[:2] == ["tzutil", "/g"]: (0, "Korea Standard Time\r\n")})
    w = winplat(tmp_path, run=run)
    assert w.default_timezone() == "Asia/Seoul"
    assert w.venv_python("C:/e/venv") == Path("C:/e/venv") / "Scripts" / "python.exe"
    assert w.console_python("C:/e/venv/Scripts/pythonw.exe").endswith("python.exe")
    h = w.hook_entry("C:/e/engine/hooks/gate.py", "C:/e/venv/Scripts/pythonw.exe")
    assert h["command"].endswith("python.exe") and h["args"] == ["C:/e/engine/hooks/gate.py"]  # 셸을 거치지 않는 실행 형식
    assert "Bash(cmdkey:*)" in w.locked_extra()
    assert w.extra_requirements() == (["tzdata"], ["tzdata"])

    class P:
        pid = 77
    w.terminate(P())
    assert run.calls[-1] == ["taskkill", "/T", "/F", "/PID", "77"]


def test_windows_timezone_map_is_valid():
    from zoneinfo import ZoneInfo
    for name, iana in win.WINDOWS_TZ.items():
        ZoneInfo(iana)  # 없는 이름이면 오류


def test_trash_moves_into_dot_trash(tmp_path):
    w = winplat(tmp_path)
    f = w.home / "a.txt"
    f.write_text("x")
    rep = {}
    dest = w.trash(f, rep)
    assert dest.parent == w.home / ".Trash" and dest.read_text() == "x" and rep["trashed"]
    f.write_text("y")
    assert w.trash(f, {}) != dest  # 같은 초에 두 번 보내도 덮지 않음


# ---------- 설치 스크립트를 윈도 층으로 ----------

def load_install():
    spec_ = importlib.util.spec_from_file_location("install_under_test", PLUGIN / "scripts" / "install.py")
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


def test_install_services_with_windows_platform(tmp_path, monkeypatch):
    inst = load_install()
    run = Runner()
    w = winplat(tmp_path, run=run)
    inst.PLAT[:] = [w]
    monkeypatch.setattr(inst, "NO_SERVICES", False)
    monkeypatch.setenv("JARVIS_HQ_DIR", str(w.home / ".jarvis-hq"))

    class A:
        no_venv, dry_run = False, False
    rep = {}
    inst.services({"label_prefix": "com.jarvis-hq"}, w.home / "py", w.home / "jarvis", A, rep, engine_changed=False, ready=True)
    creates = [c for c in run.calls if c[:2] == ["schtasks", "/Create"]]
    assert len(creates) == 3 and rep["services_manager"] == "작업 스케줄러"
    xml = (w.home / ".jarvis-hq" / "services" / "com.jarvis-hq.jarvisd.xml").read_bytes().decode("utf-16")
    assert "pythonw.exe" in xml and "jhq.daemon" not in xml  # 모듈 이름은 입구 JSON 에
    launch = json.loads((w.home / ".jarvis-hq" / "services" / "com.jarvis-hq.executor.json").read_text(encoding="utf-8"))
    assert launch["module"] == "jhq.cli" and launch["args"] == ["exec", "daemon"]
