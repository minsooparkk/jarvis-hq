"""운영체제 층의 공통 모양과 OS 와 상관없는 기본 구현."""

import os
import shutil
import subprocess
import time
from pathlib import Path


class Unsupported(RuntimeError):
    """이 운영체제에서는 할 수 없는 일."""


class ServiceSpec:
    """오래 도는 프로그램 하나(jarvisd · executor · watchdog).

    keepalive=True 면 늘 떠 있게(죽으면 다시), 아니면 interval 초마다 한 번 돈다.
    env 는 프로그램에 넘길 환경변수, log 는 표준출력·오류를 모을 파일.
    """

    def __init__(self, name, label, python, module, args=(), workdir=None, env=None, log=None, keepalive=True,
                 interval=None, engine=None):
        self.name, self.label, self.python, self.module = name, label, Path(python), module
        self.args = list(args)
        self.workdir = Path(workdir) if workdir else None
        self.env = dict(env or {})
        self.log = Path(log) if log else None
        self.keepalive, self.interval = keepalive, interval
        self.engine = Path(engine) if engine else None


class Platform:
    name = "base"
    display = "?"
    supported = False
    prompt_on_stdin = False  # claude 에 질문을 명령 인자 대신 표준입력으로(명령줄 길이·따옴표 문제가 있는 OS)
    service_word = "서비스"   # 대표에게 보이는 이름(launchd · 작업 스케줄러)
    vault_word = "금고"       # 키체인 · 자격 증명 관리자

    def __init__(self, run=None, home=None, environ=None):
        self._run = run or subprocess.run
        self.home = Path(home) if home else Path(os.path.expanduser("~"))
        self.environ = os.environ if environ is None else environ

    def unsupported(self, what):
        raise Unsupported(f"{what}: 이 운영체제는 아직 지원하지 않습니다(macOS·Windows 만).")

    def popen_kw(self):
        """하위 프로그램을 띄울 때 더할 인자(윈도: 콘솔 창을 띄우지 않음)."""
        return {}

    def cmd(self, argv, **kw):
        for k, v in self.popen_kw().items():
            kw.setdefault(k, v)
        kw.setdefault("capture_output", True)
        kw.setdefault("text", True)
        if kw.get("text"):
            kw.setdefault("encoding", "utf-8")
            kw.setdefault("errors", "replace")
        return self._run([str(a) for a in argv], **kw)

    # ---------- 서비스 ----------
    def service_files(self, spec):
        """[(파일 자리, 내용 bytes)]: 서비스 정의로 디스크에 둘 파일."""
        self.unsupported("서비스 등록")

    def service_loaded(self, label):
        self.unsupported("서비스 상태")

    def service_plan(self, spec, changed, loaded, restart):
        """돌릴 명령 목록. changed: 정의 파일이 바뀜, loaded: 이미 등록됨, restart: 엔진이 바뀌어 다시 켤 것."""
        self.unsupported("서비스 등록")

    def service_remove_plan(self, label):
        self.unsupported("서비스 내리기")

    def service_files_of(self, label, engine):
        """내릴 때 휴지통으로 보낼 정의 파일들."""
        return []

    def tolerated(self, argv):
        """실패해도 괜찮은 명령인가(등록 안 된 것을 내리기 등)."""
        return False

    def apply(self, actions):
        warnings = []
        for a in actions:
            r = self.cmd(a)
            if r.returncode != 0 and not self.tolerated(a):
                warnings.append(f"{' '.join(str(x) for x in a)}: {(r.stderr or r.stdout or '').strip()[:200]}")
        return warnings

    def service_states(self, labels):
        """{label: (상태, pid)}. 상태: running | stopped | missing."""
        self.unsupported("서비스 상태")

    def service_restart(self, label):
        """(성공 여부, 메시지)"""
        self.unsupported("서비스 다시 켜기")

    def process_uptime(self, pid):
        return None

    # ---------- 비밀값 ----------
    def secret_get(self, service, account):
        self.unsupported("비밀값 금고")

    def secret_has(self, service, account):
        self.unsupported("비밀값 금고")

    def secret_put(self, service, account, value):
        self.unsupported("비밀값 금고")

    def secret_delete(self, service, account):
        self.unsupported("비밀값 금고")

    # ---------- 파일 ----------
    def user_bin(self):
        return self.home / ".local" / "bin"

    def install_cli(self, engine, python, report):
        self.unsupported("jarvis 명령 설치")

    def cli_path(self, engine):
        """설치 스크립트·데몬이 부를 jarvis 명령 파일."""
        return Path(engine) / "bin" / "jarvis"

    def remove_cli(self, engine, report, dry=False):
        return []

    def link_dir(self, link, target_rel):
        """link 가 target_rel(link 의 부모 기준) 폴더를 가리키게. 만든 설명 또는 None(이미 있음)."""
        self.unsupported("폴더 연결")

    def trash_dir(self):
        return self.home / ".Trash"

    def trash(self, path, report=None, dry=False):
        """지우는 대신 휴지통으로. 옮긴 자리(없으면 None)."""
        path = Path(path)
        if not path.exists() and not path.is_symlink():
            return None
        dest = self.trash_dir() / f"{path.name}-{time.strftime('%Y%m%d-%H%M%S')}"
        n = 1
        while dest.exists():
            n += 1
            dest = self.trash_dir() / f"{path.name}-{time.strftime('%Y%m%d-%H%M%S')}-{n}"
        if report is not None:
            report.setdefault("trashed", []).append(f"{path} → {dest}")
        if not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dest))
        return dest

    # ---------- 프로그램 ----------
    def bash(self):
        """실행 대상·예약 스크립트를 돌릴 bash."""
        return "/bin/bash"

    def sh(self):
        return "/bin/sh"

    def venv_python(self, venv):
        return Path(venv) / "bin" / "python"

    def console_python(self, exe):
        """표준출력이 있는 파이썬(훅·실행 대상이 쓸 것)."""
        return str(exe)

    def service_python(self, venv):
        """서비스가 쓸 파이썬(창이 뜨지 않는 것)."""
        return self.venv_python(venv)

    def find_claude(self):
        return shutil.which("claude", path=self.environ.get("PATH")) or (
            str(self.user_bin() / "claude") if (self.user_bin() / "claude").exists() else None)

    def claude_argv(self, configured):
        return [configured or "claude"]

    def terminate(self, proc):
        """멈추라고 알린다(맥: SIGTERM)."""
        proc.terminate()

    def kill(self, proc):
        """곧바로 끝낸다."""
        proc.kill()

    def lock(self, fh):
        import fcntl
        fcntl.flock(fh, fcntl.LOCK_EX)

    def unlock(self, fh):
        import fcntl
        fcntl.flock(fh, fcntl.LOCK_UN)

    def default_timezone(self):
        """시스템 시간대(IANA 이름) 또는 None."""
        tz = (self.environ.get("TZ") or "").lstrip(":")
        return tz if "/" in tz and not tz.startswith("/") else None

    def extra_requirements(self):
        """이 OS 에서 엔진 venv 에 더 받을 패키지(pip 표기)와 확인할 모듈 이름."""
        return [], []

    def hook_entry(self, gate, python):
        """홈 settings.json 에 걸 문지기 훅 한 칸."""
        return {"type": "command", "command": f"{python} '{gate}'", "timeout": 20}

    def locked_extra(self):
        """이 OS 에만 있는 잠금 거부 규칙(권한)."""
        return ()

    def agent_path(self, engine):
        """claude 세션·예약 스크립트의 PATH 앞에 더할 폴더."""
        return [str(self.user_bin()), str(Path(engine) / "bin")]

    def default_path(self):
        return "/usr/bin:/bin:/usr/sbin:/sbin"


class UnsupportedPlatform(Platform):
    """macOS·Windows 가 아닌 곳. 깔거나 서비스·금고를 쓰려 하면 Unsupported 를 낸다. 파일 잠금 같은 것은 POSIX 그대로."""

    name = "unsupported"
    display = "지원하지 않는 운영체제"


def write_if_changed(path, text, mode=None, encoding="utf-8"):
    """내용이 다를 때만 쓴다. 바뀌었으면 True."""
    path = Path(path)
    data = text.encode(encoding) if isinstance(text, str) else text
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mode:
        os.chmod(path, mode)
    return True
