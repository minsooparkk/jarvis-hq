"""macOS: launchd(사용자 LaunchAgents) · 키체인(security 명령) · ~/.Trash · 심볼릭 링크.

이름은 예전 그대로 둔다(이미 설치한 사람과 맞게): launchd 라벨 <label_prefix>.<서비스>, 키체인 <keychain_prefix><이름>.
"""

import os
import plistlib
from pathlib import Path

from .base import Platform, write_if_changed


class Mac(Platform):
    name = "mac"
    display = "macOS"
    supported = True
    service_word = "launchd"
    vault_word = "키체인"

    def __init__(self, run=None, home=None, environ=None, uid=None):
        super().__init__(run, home, environ)
        self.uid = uid if uid is not None else os.getuid()

    # ---------- 서비스(launchd) ----------
    def plist_path(self, label):
        return self.home / "Library" / "LaunchAgents" / f"{label}.plist"

    def plist(self, spec):
        d = {"Label": spec.label, "ProgramArguments": [str(spec.python), "-u", "-m", spec.module, *spec.args],
             "WorkingDirectory": str(spec.workdir), "RunAtLoad": True, "EnvironmentVariables": dict(spec.env),
             "StandardOutPath": str(spec.log), "StandardErrorPath": str(spec.log)}
        if spec.keepalive:
            d["KeepAlive"] = True
            d["ThrottleInterval"] = 30
        else:
            d["StartInterval"] = int(spec.interval or 300)
        return plistlib.dumps(d)

    def service_files(self, spec):
        return [(self.plist_path(spec.label), self.plist(spec))]

    def service_files_of(self, label, engine):
        return [self.plist_path(label)]

    def target(self, label):
        return f"gui/{self.uid}/{label}"

    def service_loaded(self, label):
        return self.cmd(["launchctl", "print", self.target(label)]).returncode == 0

    def service_plan(self, spec, changed, loaded, restart):
        if changed or not loaded:
            return [["launchctl", "bootout", self.target(spec.label)],
                    ["launchctl", "bootstrap", f"gui/{self.uid}", str(self.plist_path(spec.label))]]
        if restart and spec.keepalive:
            return [["launchctl", "kickstart", "-k", self.target(spec.label)]]
        return []

    def service_remove_plan(self, label):
        return [["launchctl", "bootout", self.target(label)]]

    def tolerated(self, argv):
        return len(argv) > 1 and argv[1] == "bootout"

    def launchd_jobs(self):
        out = self.cmd(["launchctl", "list"], timeout=20).stdout or ""
        jobs = {}
        for line in out.splitlines()[1:]:
            pid, _status, lab = (line.split("\t") + ["", "", ""])[:3]
            jobs[lab] = pid if pid not in ("-", "") else None
        return jobs

    def service_states(self, labels):
        jobs = self.launchd_jobs()
        out = {}
        for lab in labels:
            if lab not in jobs:
                out[lab] = ("missing", None)
            else:
                out[lab] = ("running" if jobs[lab] else "stopped", jobs[lab])
        return out

    def service_restart(self, label):
        r = self.cmd(["launchctl", "kickstart", "-k", self.target(label)], timeout=30)
        return r.returncode == 0, (r.stderr or r.stdout or "").strip()[:200]

    def process_uptime(self, pid):
        if not pid:
            return None
        try:
            out = self.cmd(["ps", "-o", "etime=", "-p", str(pid)], timeout=10).stdout.strip()
            days, _, rest = out.rpartition("-")
            secs = 0
            for x in rest.split(":"):
                secs = secs * 60 + int(x)
            return secs + (int(days) * 86400 if days else 0)
        except (ValueError, OSError, AttributeError):
            return None

    # ---------- 키체인 ----------
    def secret_get(self, service, account):
        r = self.cmd(["security", "find-generic-password", "-a", account, "-s", service, "-w"])
        v = (r.stdout or "").strip()
        return v if r.returncode == 0 and v else None

    def secret_has(self, service, account):
        return self.cmd(["security", "find-generic-password", "-a", account, "-s", service]).returncode == 0

    def secret_put(self, service, account, value):
        """값이 명령 인자(ps 에 보임)로 나가지 않게 security -i 의 표준입력으로 넘긴다."""
        q = lambda v: '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'  # noqa: E731
        line = f"add-generic-password -U -a {q(account)} -s {q(service)} -l {q(service)} -w {q(value)}\n"
        r = self.cmd(["security", "-i"], input=line)
        if r.returncode != 0 or "error" in (r.stderr or "").lower():
            raise RuntimeError("키체인에 넣지 못했습니다: " + (r.stderr or r.stdout or "").strip()[:200])
        return True

    def secret_delete(self, service, account):
        return self.cmd(["security", "delete-generic-password", "-a", account, "-s", service]).returncode == 0

    # ---------- 파일 ----------
    def install_cli(self, engine, python, report):
        e = Path(engine)
        wrapper = (f'#!/bin/sh\n# Jarvis 명령(설치 스킬이 만든 파일)\nexport JARVIS_HQ_DIR="{e}"\n'
                   f'export PYTHONPATH="{e / "engine"}${{PYTHONPATH:+:$PYTHONPATH}}"\nexec "{python}" -m jhq.cli "$@"\n')
        write_if_changed(e / "bin" / "jarvis", wrapper, 0o755)
        link = self.user_bin() / "jarvis"
        target = e / "bin" / "jarvis"
        if link.is_symlink() and Path(os.readlink(link)) == target:
            report["cli"] = f"{link} (있음)"
        elif link.exists() or link.is_symlink():
            report["cli"] = f"{link} 에 다른 파일이 있어 그대로 둠. 대신 {target} 을 쓰세요"
            report.setdefault("warnings", []).append(report["cli"])
        else:
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
            report["cli"] = f"{link} → {target}"
        return target

    def remove_cli(self, engine, report, dry=False):
        link = self.user_bin() / "jarvis"
        if link.is_symlink() and Path(os.readlink(link)) == Path(engine) / "bin" / "jarvis":
            return [self.trash(link, report, dry)]
        return []

    def link_dir(self, link, target_rel):
        link = Path(link)
        if link.exists() or link.is_symlink():
            return None
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(Path(target_rel))
        return f"{link.parent.name}/{link.name} → {target_rel}"

    # ---------- 프로그램 ----------
    def default_timezone(self):
        tz = super().default_timezone()
        if tz:
            return tz
        try:
            real = os.readlink("/etc/localtime")
        except OSError:
            return None
        return real.split("zoneinfo/", 1)[1] if "zoneinfo/" in real else None

    def hook_entry(self, gate, python):
        # 맥 기본 python3(표준 라이브러리만). 예전 설치와 같은 줄이라 권한 파일이 바뀌지 않는다
        return {"type": "command", "command": f"/usr/bin/python3 '{gate}'", "timeout": 20}

    def agent_path(self, engine):
        return [str(self.user_bin()), str(Path(engine) / "bin"), "/opt/homebrew/bin", "/usr/local/bin"]

    def service_path(self, engine):
        return f"{self.home}/.local/bin:{engine}/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

