"""비밀값 금고(맥 키체인 · 윈도 자격 증명 관리자). 값은 화면에 찍지 않고 파일에 적지 않는다.

이름은 짧은 이름(telegram-bot-token, seal-key …)을 쓰고, 금고 항목은 <keychain_prefix><이름>, 계정은 keychain_account.
OS 마다 다른 부분은 jhq.platform 이 맡는다.
시험에서는 JARVIS_HQ_FAKE_KEYCHAIN=<json 파일> 로 가짜 금고를 쓴다(실제 금고를 건드리지 않음).
"""

import json
import os
from pathlib import Path

from . import config

TELEGRAM = "telegram-bot-token"
SEAL = "seal-key"
SLACK_BOT, SLACK_APP, DISCORD = "slack-bot-token", "slack-app-token", "discord-bot-token"
KNOWN = (TELEGRAM, SEAL)
ALIASES = {"telegram": TELEGRAM, "텔레그램": TELEGRAM, "slack-bot": SLACK_BOT, "slack-app": SLACK_APP,
           "discord": DISCORD, "디스코드": DISCORD}


def _fake():
    p = os.environ.get("JARVIS_HQ_FAKE_KEYCHAIN")
    return Path(p) if p else None


def _read_fake(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def service(name, cfg=None):
    cfg = cfg or config.load()
    return f"{cfg['keychain_prefix']}{name}"


def get(name, cfg=None):
    """값 또는 None. 부른 프로그램 안에서만 쓴다."""
    cfg = cfg or config.load()
    fake = _fake()
    if fake:
        return _read_fake(fake).get(name)
    return config.plat().secret_get(service(name, cfg), cfg["keychain_account"])


def has(name, cfg=None):
    cfg = cfg or config.load()
    fake = _fake()
    if fake:
        return bool(_read_fake(fake).get(name))
    return config.plat().secret_has(service(name, cfg), cfg["keychain_account"])


def put(name, value, cfg=None):
    """값을 넣거나 바꾼다. 값이 명령 인자(남이 볼 수 있는 프로세스 목록)로 나가지 않게 한다(OS 층이 지킴)."""
    if not value or "\n" in value:
        raise ValueError("빈 값이거나 줄바꿈이 들어 있습니다")
    cfg = cfg or config.load()
    fake = _fake()
    if fake:
        d = _read_fake(fake)
        d[name] = value
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text(json.dumps(d), encoding="utf-8")
        return True
    return config.plat().secret_put(service(name, cfg), cfg["keychain_account"], value)


def delete(name, cfg=None):
    cfg = cfg or config.load()
    fake = _fake()
    if fake:
        d = _read_fake(fake)
        found = d.pop(name, None) is not None
        fake.write_text(json.dumps(d), encoding="utf-8")
        return found
    return config.plat().secret_delete(service(name, cfg), cfg["keychain_account"])


def ensure_seal_key(cfg=None):
    """승인 서명 열쇠가 없으면 무작위로 만든다(아무에게도 보이지 않음). 만들었으면 True."""
    if has(SEAL, cfg):
        return False
    put(SEAL, os.urandom(32).hex(), cfg)
    return True
