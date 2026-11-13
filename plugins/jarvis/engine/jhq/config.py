"""설정과 경로 한 곳.

엔진 자리(기본 ~/.jarvis-hq)의 config.json 을 읽는다. 비밀값은 여기에 적지 않는다(맥 키체인·윈도 자격 증명 관리자, jhq.secrets).
시험이나 다른 자리에 설치할 때는 환경변수 JARVIS_HQ_DIR 로 엔진 자리를 바꾼다.
"""

import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent  # .../engine
VERSION = (ENGINE_ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ENGINE_ROOT / "VERSION").exists() else "0"

DEFAULTS = {
    "home": "~/jarvis",
    "label_prefix": "com.jarvis-hq",
    "keychain_account": "jarvis-hq",
    "keychain_prefix": "jarvis-hq.",
    "timezone": "Asia/Seoul",
    "assistant_name": "Jarvis",
    "owner_title": "대표",
    "claude": "claude",
    "agent_timeout_min": 20,
    "executor_tick_sec": 30,
    "messenger": "telegram",  # telegram | slack | discord (없으면 텔레그램: 예전 설치 그대로)
    "telegram": {"owner_id": None, "group_id": None, "topics": {}},
    "slack": {"owner_id": None, "team_id": None},
    "discord": {"owner_id": None},
}


def engine_dir():
    return Path(os.environ.get("JARVIS_HQ_DIR") or (Path.home() / ".jarvis-hq"))


def config_path():
    return engine_dir() / "config.json"


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    p = Path(path) if path else config_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    return _merge(DEFAULTS, data)


def save(cfg, path=None):
    p = Path(path) if path else config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(p, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


def write_atomic(path, text, tmp_suffix=".tmp"):
    """임시 파일에 쓰고 바꿔 끼운다(utf-8). 윈도는 다른 프로그램이 그 파일을 잠깐 열고 있으면 바꿔 끼우기가
    실패해서 몇 번 다시 해 본다."""
    import time
    path = Path(path)
    tmp = path.with_name(path.name + tmp_suffix)
    tmp.write_text(text, encoding="utf-8")
    for i in range(5):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if i == 4:
                raise
            time.sleep(0.05 * (i + 1))


class Paths:
    """사용자 Jarvis 홈과 그 안 .harness 의 자리."""

    def __init__(self, cfg=None):
        cfg = cfg or load()
        self.cfg = cfg
        self.home = Path(os.path.expanduser(str(cfg["home"])))
        h = self.home / ".harness"
        self.harness = h
        self.log = h / "log"            # 한 일 기록(날짜별)
        self.decisions = h / "decisions"  # 대표 결정
        self.memory = h / "memory"      # 배운 것
        self.ledger = h / "ledger"      # 장부(실행 요청·보낼 글 DB)
        self.state = h / "state"        # 데몬 상태·로그
        self.work = h / "work"          # 작업 폴더(코드 작업 등)
        self.inbox = h / "inbox"        # 메신저로 받은 파일
        self.logs = self.state / "logs"
        self.executor_db = self.ledger / "executor.db"
        self.outbox_db = self.ledger / "outbox.db"
        self.attach = self.ledger / "attach"
        self.attempts = self.ledger / "attempts"
        self.pause = self.state / "executor.pause"
        self.heartbeat = self.state / "jarvisd.heartbeat"
        self.daemon_state = self.state / "jarvisd.json"
        self.targets = self.home / "hooks" / "targets.yaml"
        self.gate = self.home / "hooks" / "gate.json"
        self.permissions = self.home / "hooks" / "permissions.json"
        self.settings = self.home / ".claude" / "settings.json"
        self.schedule = self.home / "schedule.yaml"
        self.skills = self.home / "skills"

    def ensure(self):
        for d in (self.log, self.decisions, self.memory, self.ledger, self.state, self.work, self.inbox, self.logs,
                  self.attach, self.attempts):
            d.mkdir(parents=True, exist_ok=True)
        return self


def tz(cfg=None):
    """설정한 시간대. 시간대 자료가 없는 파이썬(윈도에 tzdata 가 없을 때)이면 이 컴퓨터의 지금 시차로 대신한다."""
    name = (cfg or load()).get("timezone") or "Asia/Seoul"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001  zoneinfo 자료가 없는 파이썬
        local = datetime.now().astimezone().tzinfo
        return local or timezone(timedelta(hours=9))


def valid_timezone(name):
    """IANA 이름(예: Asia/Seoul)이 이 파이썬에서 맞는지. 시간대 자료가 없어 모르면 꼴만 본다."""
    name = str(name or "").strip()
    if not name or " " in name:
        return False
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError:
        return "/" in name or name == "UTC"
    try:
        ZoneInfo(name)
        return True
    except ZoneInfoNotFoundError:
        try:
            import zoneinfo
            return not zoneinfo.available_timezones() and ("/" in name or name == "UTC")
        except Exception:  # noqa: BLE001
            return False
    except (ValueError, OSError):
        return False


_PLAT = []


def plat():
    """이 컴퓨터의 운영체제 층(jhq.platform). 한 번 만들어 같이 쓴다."""
    if not _PLAT:
        from . import platform as osplat
        _PLAT.append(osplat.current())
    return _PLAT[0]


def now(cfg=None):
    return datetime.now(tz(cfg))


def stamp(cfg=None):
    return now(cfg).isoformat(timespec="seconds")


def label(cfg, name):
    """서비스 이름(맥 launchd 라벨·윈도 작업 이름): <prefix>.jarvisd · executor · watchdog"""
    return f"{cfg['label_prefix']}.{name}"
