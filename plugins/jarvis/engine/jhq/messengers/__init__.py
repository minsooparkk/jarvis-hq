"""메신저 층. 데몬·지킴이·명령은 텔레그램·Slack·Discord API 를 직접 알지 않고 여기서 고른 Messenger 를 쓴다.

config.json 의 messenger: telegram(기본, 예전 설치 그대로) | slack | discord.
이 파일은 표준 라이브러리만 쓴다(설치 스크립트가 불러 메신저마다 필요한 비밀값·패키지를 본다).
각 메신저 구현(telegram.py · slack.py · discord.py)은 쓸 때만 불러온다.

보안 약속(docs/보안-모델.md)은 메신저마다 같다.
- 받는 글·버튼은 설정한 대표 계정이 대표 DM(텔레그램은 설정한 그룹도)에서 보낸 것만. 다른 사람 것은 버린다.
- 승인은 대표 계정의 버튼 눌림으로만. 버튼에는 순번(b:0 …)만 싣고, 값('R-n|봉인')은 장부(outbox.db posts)에 둔다.
  글자 '승인' 은 승인이 아니다. 봉인 대조와 서명은 실행기 코드(jhq.executor.decide)가 한다.
"""

from .. import config, secrets

SPECS = {
    "telegram": {"display": "텔레그램", "secrets": [secrets.TELEGRAM], "packages": [], "modules": [],
                 "owner_word": "chat id", "secret_hint": "jarvis secret set telegram"},
    "slack": {"display": "Slack", "secrets": [secrets.SLACK_BOT, secrets.SLACK_APP],
              "packages": ["websocket-client>=1.6,<2"], "modules": ["websocket"], "owner_word": "Slack 멤버 ID",
              "secret_hint": "jarvis secret set slack-bot · jarvis secret set slack-app"},
    "discord": {"display": "Discord", "secrets": [secrets.DISCORD], "packages": ["websocket-client>=1.6,<2"],
                "modules": ["websocket"], "owner_word": "Discord 사용자 ID", "secret_hint": "jarvis secret set discord"},
}
NAMES = tuple(SPECS)


class NotReady(RuntimeError):
    """토큰이나 대표 id 가 없어 연결할 수 없음."""


def kind(cfg):
    m = str((cfg or {}).get("messenger") or "telegram").strip().lower()
    if m not in SPECS:
        raise NotReady(f"모르는 메신저입니다: {m} (telegram · slack · discord)")
    return m


def spec(cfg_or_name):
    return SPECS[cfg_or_name if isinstance(cfg_or_name, str) else kind(cfg_or_name)]


def owner(cfg, name=None):
    """설정한 대표 id(없으면 None)."""
    name = name or kind(cfg)
    v = ((cfg or {}).get(name) or {}).get("owner_id")
    return v if v not in (None, "", 0) else None


def set_owner(cfg, value, name=None):
    name = name or kind(cfg)
    value = str(value).strip()
    if name == "telegram":
        value = int(value)
    elif name == "slack":
        if not value[:1].isalpha() or not value.isalnum():
            raise ValueError("Slack 멤버 ID 모양(영문 대문자로 시작, 예: U 로 시작하는 글자)이 아닙니다")
        value = value.upper()
    elif name == "discord" and not value.isdigit():
        raise ValueError("Discord 사용자 ID 는 숫자입니다(개발자 모드에서 '사용자 ID 복사')")
    cfg.setdefault(name, {})["owner_id"] = value
    return value


def check_secret(name, value):
    """비밀값 모양 확인. 틀리면 알릴 글, 맞으면 None."""
    if name == secrets.TELEGRAM and ":" not in value:
        return "텔레그램 봇 토큰 모양(숫자:글자)이 아닙니다. BotFather 가 준 값을 그대로 붙여 넣으세요."
    if name == secrets.SLACK_BOT and not value.startswith("xoxb-"):
        return "Slack 봇 토큰은 xoxb- 로 시작합니다(OAuth & Permissions 화면의 Bot User OAuth Token)."
    if name == secrets.SLACK_APP and not value.startswith("xapp-"):
        return "Slack 앱 토큰은 xapp- 로 시작합니다(Basic Information 화면의 App-Level Tokens)."
    if name == secrets.DISCORD and value.count(".") < 2:
        return "Discord 봇 토큰 모양(점 두 개로 나뉜 글)이 아닙니다. 개발자 포털 Bot 화면의 Reset Token 으로 받은 값을 넣으세요."
    return None


def missing(cfg, name=None):
    """연결에 모자란 것 목록(사람이 읽는 글)."""
    name = name or kind(cfg)
    out = [f"{n}(금고)" for n in SPECS[name]["secrets"] if not secrets.has(n, cfg)]
    if not owner(cfg, name):
        out.append(f"대표 {SPECS[name]['owner_word']}")
    return out


def connect(cfg, name=None, **kw):
    """설정과 금고로 Messenger 를 만든다. 모자라면 NotReady."""
    name = name or kind(cfg)
    toks = {n: secrets.get(n, cfg) for n in SPECS[name]["secrets"]}
    if not all(toks.values()):
        raise NotReady(f"{SPECS[name]['display']} 토큰이 금고에 없습니다. 대표 터미널에서: {SPECS[name]['secret_hint']}")
    if name == "telegram":
        from . import telegram
        return telegram.TelegramMessenger(telegram.Bot(toks[secrets.TELEGRAM], **kw), cfg)
    if name == "slack":
        from . import slack
        return slack.SlackMessenger(slack.SlackApi(toks[secrets.SLACK_BOT], toks[secrets.SLACK_APP], **kw), cfg)
    from . import discord
    return discord.DiscordMessenger(discord.DiscordApi(toks[secrets.DISCORD], **kw), cfg)


def notify_owner(cfg, text):
    """데몬을 거치지 않고 대표 DM 에 글 하나(지킴이용). 보냈으면 True."""
    try:
        if not owner(cfg):
            return False
        m = connect(cfg)
        m.send("dm", text)
        return True
    except Exception as e:  # noqa: BLE001
        import sys
        print("알림 실패:", str(e)[:200], file=sys.stderr)
        return False


def label(cfg):
    return SPECS[kind(cfg)]["display"] if (cfg or {}).get("messenger", "telegram") in SPECS else "메신저"


__all__ = ["SPECS", "NAMES", "NotReady", "kind", "spec", "owner", "set_owner", "check_secret", "missing", "connect",
           "notify_owner", "label", "config"]
