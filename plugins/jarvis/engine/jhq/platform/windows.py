"""Windows: 작업 스케줄러(현재 사용자, 관리자 권한 없이) · 자격 증명 관리자(ctypes) · 디렉터리 정션 · Git Bash.

고른 것과 이유
- 서비스: 작업 스케줄러. jarvisd·실행기는 '로그온할 때 시작' 작업(실행 시간 제한 없음, 실패하면 1분 뒤 다시),
  지킴이는 5분마다 도는 작업. 창 없는 pythonw.exe 로 돌고, 환경변수·로그는 작업에 못 적어서 엔진의
  platform/winlaunch.py 가 설정 JSON(<엔진>/services/<이름>.json)을 읽어 맞춘다. 작업 정의는 XML(UTF-16)로 등록한다.
- 비밀값: 자격 증명 관리자(Generic 자격 증명, 이 컴퓨터의 이 사용자만). keyring 패키지 대신 ctypes 로 직접 부른다.
  keyring 은 설치된 백엔드에 따라 평문 파일 금고로 조용히 바뀔 수 있어서다. 값 크기 한도는 2560바이트.
- 휴지통: 사용자 폴더의 .Trash 폴더로 옮긴다(맥과 같은 자리 이름). 윈도 휴지통 API 는 크기가 크거나 네트워크 드라이브면
  알리지 않고 영구 삭제할 수 있어 쓰지 않는다.
- 셸: 실행 대상·예약 스크립트는 Git Bash 로 돈다(맥과 같은 bash 문법). Git for Windows 가 꼭 있어야 한다.
- 이 기계(맥)에서는 윈도 실행을 시험할 수 없다. 가짜 실행기·가짜 금고로 만드는 명령과 파일만 시험한다.
  실제 기기에서 볼 것: docs/윈도우-확인할-것.md
"""

import base64
import json
import os
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

from .base import Platform, Unsupported, write_if_changed

CREATE_NO_WINDOW = 0x08000000
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
BLOB_MAX = 2560  # CRED_MAX_CREDENTIAL_BLOB_SIZE
MARK = "jarvis-hq"  # 바로가기 파일에 넣는 표시(우리가 만든 것만 지운다)

# Windows 시간대 이름 → IANA(CLDR windowsZones 의 대표 지역). 없는 것은 설치 때 묻는다.
WINDOWS_TZ = {
    "Korea Standard Time": "Asia/Seoul", "Tokyo Standard Time": "Asia/Tokyo", "China Standard Time": "Asia/Shanghai",
    "Taipei Standard Time": "Asia/Taipei", "Singapore Standard Time": "Asia/Singapore", "SE Asia Standard Time": "Asia/Bangkok",
    "India Standard Time": "Asia/Kolkata", "Sri Lanka Standard Time": "Asia/Colombo", "Nepal Standard Time": "Asia/Kathmandu",
    "Bangladesh Standard Time": "Asia/Dhaka", "Myanmar Standard Time": "Asia/Yangon", "Pakistan Standard Time": "Asia/Karachi",
    "West Asia Standard Time": "Asia/Tashkent", "Afghanistan Standard Time": "Asia/Kabul", "Iran Standard Time": "Asia/Tehran",
    "Arabian Standard Time": "Asia/Dubai", "Arab Standard Time": "Asia/Riyadh", "Israel Standard Time": "Asia/Jerusalem",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar", "North Asia Standard Time": "Asia/Krasnoyarsk",
    "North Asia East Standard Time": "Asia/Irkutsk", "Yakutsk Standard Time": "Asia/Yakutsk",
    "Vladivostok Standard Time": "Asia/Vladivostok", "W. Australia Standard Time": "Australia/Perth",
    "AUS Central Standard Time": "Australia/Darwin", "Cen. Australia Standard Time": "Australia/Adelaide",
    "E. Australia Standard Time": "Australia/Brisbane", "AUS Eastern Standard Time": "Australia/Sydney",
    "Tasmania Standard Time": "Australia/Hobart", "West Pacific Standard Time": "Pacific/Port_Moresby",
    "New Zealand Standard Time": "Pacific/Auckland", "Fiji Standard Time": "Pacific/Fiji",
    "Hawaiian Standard Time": "Pacific/Honolulu", "Alaskan Standard Time": "America/Anchorage",
    "Pacific Standard Time": "America/Los_Angeles", "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time": "America/Denver", "Central Standard Time": "America/Chicago",
    "Central Standard Time (Mexico)": "America/Mexico_City", "Canada Central Standard Time": "America/Regina",
    "Eastern Standard Time": "America/New_York", "SA Pacific Standard Time": "America/Bogota",
    "Venezuela Standard Time": "America/Caracas", "Atlantic Standard Time": "America/Halifax",
    "Newfoundland Standard Time": "America/St_Johns", "SA Eastern Standard Time": "America/Cayenne",
    "E. South America Standard Time": "America/Sao_Paulo", "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "Pacific SA Standard Time": "America/Santiago", "UTC": "Etc/UTC", "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik", "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris", "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw", "GTB Standard Time": "Europe/Bucharest",
    "FLE Standard Time": "Europe/Kiev", "E. Europe Standard Time": "Europe/Chisinau",
    "Russian Standard Time": "Europe/Moscow", "Turkey Standard Time": "Europe/Istanbul",
    "Egypt Standard Time": "Africa/Cairo", "South Africa Standard Time": "Africa/Johannesburg",
    "W. Central Africa Standard Time": "Africa/Lagos", "E. Africa Standard Time": "Africa/Nairobi",
}


class WinVault:
    """advapi32 의 CredWriteW·CredReadW·CredDeleteW 를 ctypes 로. Generic 자격 증명, 대상 이름 = 금고 항목 이름."""

    TYPE_GENERIC, PERSIST_LOCAL_MACHINE, ERROR_NOT_FOUND = 1, 2, 1168

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR), ("LastWritten", FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

        self.CREDENTIAL = CREDENTIAL
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        self._write = adv.CredWriteW
        self._write.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
        self._write.restype = wintypes.BOOL
        self._read = adv.CredReadW
        self._read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        self._read.restype = wintypes.BOOL
        self._delete = adv.CredDeleteW
        self._delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._delete.restype = wintypes.BOOL
        self._free = adv.CredFree
        self._free.argtypes = [ctypes.c_void_p]

    def read(self, target):
        """(사용자 이름, 값 bytes) 또는 None."""
        ct = self.ctypes
        p = ct.POINTER(self.CREDENTIAL)()
        if not self._read(target, self.TYPE_GENERIC, 0, ct.byref(p)):
            err = ct.get_last_error()
            if err == self.ERROR_NOT_FOUND:
                return None
            raise OSError(err, "CredReadW 실패")
        try:
            c = p.contents
            blob = ct.string_at(c.CredentialBlob, c.CredentialBlobSize) if c.CredentialBlobSize else b""
            return (c.UserName or ""), blob
        finally:
            self._free(p)

    def write(self, target, user, blob):
        ct = self.ctypes
        buf = (ct.c_ubyte * len(blob)).from_buffer_copy(blob)
        c = self.CREDENTIAL()
        c.Type, c.TargetName, c.UserName = self.TYPE_GENERIC, target, user
        c.CredentialBlobSize, c.CredentialBlob = len(blob), ct.cast(buf, ct.POINTER(ct.c_ubyte))
        c.Persist = self.PERSIST_LOCAL_MACHINE
        if not self._write(ct.byref(c), 0):
            raise OSError(ct.get_last_error(), "CredWriteW 실패")

    def delete(self, target):
        if self._delete(target, self.TYPE_GENERIC, 0):
            return True
        if self.ctypes.get_last_error() == self.ERROR_NOT_FOUND:
            return False
        raise OSError(self.ctypes.get_last_error(), "CredDeleteW 실패")


class Windows(Platform):
    name = "windows"
    display = "Windows"
    supported = True
    prompt_on_stdin = True  # 명령줄 길이 한도(약 3만 2천 자)와 따옴표 처리 차이를 피한다
    service_word = "작업 스케줄러"
    vault_word = "자격 증명 관리자"

    def __init__(self, run=None, home=None, environ=None, vault=None, exists=None):
        super().__init__(run, home, environ)
        self._vault = vault
        self.exists = exists or os.path.exists

    @property
    def vault(self):
        if self._vault is None:
            self._vault = WinVault()
        return self._vault

    def popen_kw(self):
        return {"creationflags": CREATE_NO_WINDOW}

    # ---------- 서비스(작업 스케줄러) ----------
    def user_id(self):
        user = self.environ.get("USERNAME") or os.path.basename(str(self.home))
        dom = self.environ.get("USERDOMAIN")
        return f"{dom}\\{user}" if dom else user

    def files_for(self, label, engine):
        d = Path(engine) / "services"
        return d / f"{label}.xml", d / f"{label}.json"

    def launcher(self, spec):
        return Path(spec.engine) / "engine" / "jhq" / "platform" / "winlaunch.py"

    def task_xml(self, spec):
        """작업 정의 XML(글). 등록 때는 UTF-16 으로 쓴다."""
        xml_path, json_path = self.files_for(spec.label, spec.engine)
        user = escape(self.user_id())
        if spec.keepalive:
            trigger = f"<LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger>"
            limit = "PT0S"  # 기본값(72시간)이면 데몬이 사흘마다 죽는다
            restart = "<RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>"
        else:
            every = max(60, int(spec.interval or 300))
            trigger = ("<TimeTrigger><Repetition><Interval>PT{m}M</Interval><StopAtDurationEnd>false</StopAtDurationEnd>"
                       "</Repetition><StartBoundary>2026-01-01T00:00:00</StartBoundary><Enabled>true</Enabled></TimeTrigger>"
                       ).format(m=every // 60)
            limit, restart = "PT10M", ""
        args = f'"{self.launcher(spec)}" "{json_path}"'
        return (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            f'<Task version="1.2" xmlns="{TASK_NS}">\n'
            f"  <RegistrationInfo><Description>{escape('Jarvis ' + spec.name + ' (jarvis-hq 설치 스크립트가 만듦)')}</Description>"
            f"<URI>\\{escape(spec.label)}</URI></RegistrationInfo>\n"
            f"  <Triggers>{trigger}</Triggers>\n"
            f'  <Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType>'
            "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\n"
            "  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
            "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>"
            "<AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable>"
            "<RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>"
            "<IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>"
            "<AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden>"
            "<RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun>"
            f"<ExecutionTimeLimit>{limit}</ExecutionTimeLimit><Priority>7</Priority>{restart}</Settings>\n"
            f'  <Actions Context="Author"><Exec><Command>{escape(str(spec.python))}</Command>'
            f"<Arguments>{escape(args)}</Arguments><WorkingDirectory>{escape(str(spec.workdir))}</WorkingDirectory>"
            "</Exec></Actions>\n</Task>\n")

    def launch_spec(self, spec):
        env = dict(spec.env)
        env.pop("PATH", None)  # 윈도는 사용자 PATH 를 그대로 쓰고 앞에만 더한다(winlaunch)
        return {"module": spec.module, "args": spec.args, "env": env, "log": str(spec.log), "cwd": str(spec.workdir),
                "pythonpath": str(Path(spec.engine) / "engine"),
                "path_prepend": self.agent_path(spec.engine)}

    def service_files(self, spec):
        xml_path, json_path = self.files_for(spec.label, spec.engine)
        return [(xml_path, self.task_xml(spec).encode("utf-16")),
                (json_path, (json.dumps(self.launch_spec(spec), ensure_ascii=False, indent=1) + "\n").encode("utf-8"))]

    def service_loaded(self, label):
        return self.cmd(["schtasks", "/Query", "/TN", label]).returncode == 0

    def service_plan(self, spec, changed, loaded, restart):
        xml_path, _ = self.files_for(spec.label, spec.engine)
        acts = []
        if changed or not loaded:
            acts.append(["schtasks", "/Create", "/TN", spec.label, "/XML", str(xml_path), "/F"])
        if spec.keepalive and (changed or not loaded or restart):
            acts += [["schtasks", "/End", "/TN", spec.label], ["schtasks", "/Run", "/TN", spec.label]]
        return acts

    def service_remove_plan(self, label):
        return [["schtasks", "/End", "/TN", label], ["schtasks", "/Delete", "/TN", label, "/F"]]

    def tolerated(self, argv):
        return len(argv) > 1 and argv[0] == "schtasks" and argv[1] in ("/End", "/Delete")

    def powershell(self, script, timeout=60):
        enc = base64.b64encode(script.encode("utf-16-le")).decode()
        return self.cmd(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                         "-EncodedCommand", enc], timeout=timeout)

    def service_states(self, labels):
        """상태 이름(Running·Ready·Disabled…)은 영어 열거값이라 윈도 언어와 상관없다."""
        names = ",".join("'" + str(lab).replace("'", "''") + "'" for lab in labels)
        script = ("$ErrorActionPreference='SilentlyContinue'\n"
                  f"foreach ($n in @({names})) {{ $t = Get-ScheduledTask -TaskPath '\\' -TaskName $n;"
                  " if ($t) { \"$n`t$($t.State)\" } else { \"$n`tmissing\" } }")
        r = self.powershell(script)
        seen = {}
        for line in (r.stdout or "").splitlines():
            lab, _, st = line.strip().partition("\t")
            if lab:
                seen[lab] = st.strip()
        out = {}
        for lab in labels:
            st = seen.get(lab)
            if st is None:
                out[lab] = ("unknown", None)  # 파워셸을 못 썼다: 심장박동으로만 판단
            elif st == "missing":
                out[lab] = ("missing", None)
            elif st in ("Running", "Queued"):
                out[lab] = ("running", None)
            else:
                out[lab] = ("stopped", None)
        return out

    def service_restart(self, label):
        self.cmd(["schtasks", "/End", "/TN", label], timeout=30)
        r = self.cmd(["schtasks", "/Run", "/TN", label], timeout=30)
        return r.returncode == 0, (r.stderr or r.stdout or "").strip()[:200]

    # ---------- 자격 증명 관리자 ----------
    def secret_get(self, service, account):
        got = self.vault.read(service)
        if not got:
            return None
        v = got[1].decode("utf-8", errors="replace").strip()
        return v or None

    def secret_has(self, service, account):
        return self.vault.read(service) is not None

    def secret_put(self, service, account, value):
        blob = str(value).encode("utf-8")
        if len(blob) > BLOB_MAX:
            raise RuntimeError(f"값이 너무 깁니다({len(blob)}바이트, 자격 증명 관리자 한도 {BLOB_MAX})")
        self.vault.write(service, account, blob)
        return True

    def secret_delete(self, service, account):
        return self.vault.delete(service)

    # ---------- 명령 바로가기 ----------
    def cli_path(self, engine):
        return Path(engine) / "bin" / "jarvis.cmd"

    def _cmd_text(self, engine, python):
        e, py = Path(engine), Path(python)
        try:
            rel = py.relative_to(e)
            py_ref = "%JARVIS_HQ_DIR%\\" + str(rel).replace("/", "\\")
        except ValueError:
            py_ref = str(py)
        return ("@echo off\r\nrem jarvis-hq: Jarvis command (made by the installer)\r\nsetlocal\r\n"
                'for %%I in ("%~dp0..") do set "JARVIS_HQ_DIR=%%~fI"\r\n'
                'set "PYTHONPATH=%JARVIS_HQ_DIR%\\engine"\r\nset "PYTHONUTF8=1"\r\nset "PYTHONIOENCODING=utf-8"\r\n'
                f'"{py_ref}" -m jhq.cli %*\r\n')

    def _sh_text(self, engine, python):
        e, py = posix(engine), posix(python)
        return (f'#!/bin/sh\n# {MARK}: Jarvis 명령(Git Bash 용, 설치 스킬이 만든 파일)\nexport JARVIS_HQ_DIR="{e}"\n'
                f'export PYTHONPATH="{e}/engine"\nexport PYTHONUTF8=1\nexec "{py}" -m jhq.cli "$@"\n')

    def _shims(self, engine):
        e = Path(engine)
        default = self.home / ".jarvis-hq"
        cmd_target = "%USERPROFILE%\\.jarvis-hq\\bin\\jarvis.cmd" if e == default else str(e / "bin" / "jarvis.cmd")
        return {self.user_bin() / "jarvis.cmd": f'@rem {MARK}\r\n@"{cmd_target}" %*\r\n',
                self.user_bin() / "jarvis": f'#!/bin/sh\n# {MARK}\nexec "{posix(e)}/bin/jarvis" "$@"\n'}

    def install_cli(self, engine, python, report):
        e = Path(engine)
        write_if_changed(e / "bin" / "jarvis.cmd", self._cmd_text(e, python))
        write_if_changed(e / "bin" / "jarvis", self._sh_text(e, python))
        made, kept = [], []
        for path, text in self._shims(e).items():
            if path.exists() and MARK not in path.read_text(encoding="utf-8", errors="replace"):
                kept.append(str(path))
                continue
            write_if_changed(path, text)
            made.append(str(path))
        report["cli"] = ", ".join(made) + (" (cmd·PowerShell 은 jarvis.cmd, Git Bash 는 jarvis)" if made else "")
        if kept:
            report.setdefault("warnings", []).append(f"{', '.join(kept)} 에 다른 파일이 있어 그대로 둠. 대신 {e / 'bin'} 의 것을 쓰세요")
        return self.cli_path(e)

    def remove_cli(self, engine, report, dry=False):
        out = []
        for path in self._shims(engine):
            if path.exists() and MARK in path.read_text(encoding="utf-8", errors="replace"):
                out.append(self.trash(path, report, dry))
        return out

    def link_dir(self, link, target_rel):
        """심볼릭 링크는 관리자·개발자 모드가 필요해서 디렉터리 정션(절대 경로)을 만든다."""
        link = Path(link)
        if link.exists() or link.is_symlink():
            return None
        target = (link.parent / target_rel)
        target = Path(os.path.normpath(str(target)))
        link.parent.mkdir(parents=True, exist_ok=True)
        r = self.cmd(["cmd", "/c", "mklink", "/J", str(link), str(target)])
        if r.returncode != 0:
            raise OSError(f"정션을 만들지 못했습니다({link} → {target}): {(r.stderr or r.stdout or '').strip()[:200]}")
        return f"{link.parent.name}/{link.name} → {target} (정션)"

    # ---------- 프로그램 ----------
    def bash(self):
        """Git Bash. WSL 의 bash(System32)는 쓰지 않는다."""
        env = self.environ
        cands = []
        if env.get("CLAUDE_CODE_GIT_BASH_PATH"):
            cands.append(env["CLAUDE_CODE_GIT_BASH_PATH"])
        git = shutil.which("git", path=env.get("PATH"))
        if git:
            g = Path(git).resolve().parent
            cands += [str(g.parent / "bin" / "bash.exe"), str(g.parent.parent / "bin" / "bash.exe")]
        for root in (env.get("ProgramFiles"), env.get("ProgramW6432"), env.get("ProgramFiles(x86)"),
                     os.path.join(env.get("LOCALAPPDATA") or "", "Programs") if env.get("LOCALAPPDATA") else None):
            if root:
                cands.append(os.path.join(root, "Git", "bin", "bash.exe"))
        for c in cands:
            if c and self.exists(c) and "system32" not in c.lower():
                return c
        raise Unsupported("Git for Windows(Git Bash)를 찾지 못했습니다. https://git-scm.com 에서 설치한 뒤 다시 하세요"
                          "(다른 자리에 깔았으면 환경변수 CLAUDE_CODE_GIT_BASH_PATH 에 bash.exe 경로).")

    def sh(self):
        return self.bash()

    def venv_python(self, venv):
        return Path(venv) / "Scripts" / "python.exe"

    def console_python(self, exe):
        """pythonw.exe(창 없음)에는 표준출력이 없어 훅 결과를 못 낸다. 같은 자리의 python.exe 로 바꾼다."""
        p = Path(exe)
        return str(p.with_name("python.exe")) if p.name.lower() == "pythonw.exe" else str(p)

    def service_python(self, venv):
        return Path(venv) / "Scripts" / "pythonw.exe"

    def find_claude(self):
        for c in (shutil.which("claude", path=self.environ.get("PATH")),
                  str(self.user_bin() / "claude.exe"),
                  os.path.join(self.environ.get("APPDATA") or "", "npm", "claude.cmd") if self.environ.get("APPDATA") else None):
            if c and self.exists(c):
                return c
        return None

    def claude_argv(self, configured):
        """claude.exe 는 그대로. npm 의 claude.cmd 는 받은 글이 cmd 를 거치며 깨지거나 명령으로 풀릴 수 있어
        그 뒤의 진짜 프로그램(node + cli.js 또는 패키지 안 claude.exe)을 찾아 직접 부른다."""
        p = str(configured or "claude")
        if not p.lower().endswith((".cmd", ".bat")):
            return [p]
        pkg = Path(p).parent / "node_modules" / "@anthropic-ai" / "claude-code"
        for exe in (pkg / "bin" / "claude.exe", pkg / "claude.exe"):
            if self.exists(str(exe)):
                return [str(exe)]
        cli = pkg / "cli.js"
        node = Path(p).parent / "node.exe"
        node = str(node) if self.exists(str(node)) else shutil.which("node", path=self.environ.get("PATH"))
        if node and self.exists(str(cli)):
            return [node, str(cli)]
        raise Unsupported(f"{p} 뒤의 Claude Code 프로그램을 찾지 못했습니다. Claude Code 네이티브 설치(claude.exe)를 권합니다.")

    def terminate(self, proc):
        """자식(claude 가 띄운 셸·도구)까지 같이 멈춘다. 윈도에는 SIGTERM 이 없다."""
        r = self.cmd(["taskkill", "/T", "/F", "/PID", str(proc.pid)], timeout=30)
        if r.returncode != 0:
            try:
                proc.kill()
            except OSError:
                pass

    def kill(self, proc):
        self.terminate(proc)

    def lock(self, fh):
        """파일 첫 바이트를 잠근다(덧붙이기 모드라도 쓰기는 끝에 간다). 10초 넘게 못 잡으면 OSError."""
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

    def unlock(self, fh):
        import msvcrt
        fh.flush()
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

    def default_timezone(self):
        tz = Platform.default_timezone(self)
        if tz:
            return tz
        r = self.cmd(["tzutil", "/g"], timeout=20)
        name = (r.stdout or "").strip().replace("_dstoff", "")
        return WINDOWS_TZ.get(name) if r.returncode == 0 else None

    def extra_requirements(self):
        # 윈도 파이썬에는 시간대 자료가 없어 zoneinfo 가 tzdata 패키지를 쓴다
        return ["tzdata"], ["tzdata"]

    def hook_entry(self, gate, python):
        # 실행 형식(command + args): 셸을 거치지 않아 Git Bash·PowerShell 어느 쪽이든 같고, 경로 따옴표 문제가 없다
        return {"type": "command", "command": self.console_python(python), "args": [str(gate)], "timeout": 20}

    def locked_extra(self):
        return ("Read(~/AppData/Roaming/Microsoft/Credentials/**)", "Read(~/AppData/Local/Microsoft/Credentials/**)",
                "Read(~/AppData/Roaming/Microsoft/Protect/**)", "Bash(cmdkey:*)")

    def agent_path(self, engine):
        return [str(self.user_bin()), str(Path(engine) / "bin")]

    def default_path(self):
        return ""

    def service_path(self, engine):
        return ""


def posix(p):
    """Git Bash 가 읽는 꼴(C:/Users/...)."""
    return str(p).replace("\\", "/")
