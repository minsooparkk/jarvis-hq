"""Discord: 게이트웨이(웹소켓, v10) 받기 + REST 보내기. 대표와 봇의 DM 만 쓴다.

- intent 는 DIRECT_MESSAGES(1<<12) 하나. 공식 문서(docs.discord.com, 2026-11-13 읽음): 메시지 내용 intent(특권)는
  'DM 으로 앱에 온 글' 에는 필요 없다(예외로 적혀 있음). 버튼 눌림(INTERACTION_CREATE)은 intent 와 상관없이 온다.
  단 개발자 포털의 Interactions Endpoint URL 을 비워 둬야 게이트웨이로 온다.
- 봇은 대표와 같은 서버에 있어야 DM 을 보낼 수 있다(대표 혼자 쓰는 비공개 서버에 봇을 넣는다).
- 받기 거르기: 서버(guild) 글은 버린다. 대표 사용자 ID 가 대표 DM 채널에서 보낸 글·누른 버튼만.
  다른 사람의 눌림에는 '권한이 없습니다' 를 그 사람에게만 보이게(ephemeral) 답하고 아무것도 바꾸지 않는다.
- 버튼: custom_id 는 순번 'b:0'…(100자 한도). 값('R-n|봉인')은 장부에 둔다(텔레그램과 같음).
  눌림에는 3초 안에 응답해야 한다(type 6: 받음만, type 4 + flags 64: 그 사람에게만 보이는 글).
- 글 2000자 한도 → 1900자씩, ``` 울타리는 조각마다 닫고 연다. 429 는 retry_after 만큼 기다린다.
- 하트비트·RESUME·다시 연결은 이 파일이 한다. 4004(인증 실패)·4010~4014 는 다시 붙지 않고 멈춘다.
실제 Discord 에 붙여 본 적은 없다(토큰 없음). 점검표: docs/메신저-확인할-것.md
"""

import json
import random
import threading
import time
import urllib.parse
from pathlib import Path

from . import base, ws

API = "https://discord.com/api/v10"
UA = "DiscordBot (https://example.invalid/jarvis-hq, 1)"
INTENTS = 1 << 12  # DIRECT_MESSAGES
LIMIT = 1900
SEND_FILE_MAX = 10 * 1024 * 1024
FATAL = (4004, 4010, 4011, 4012, 4013, 4014)
FILE_HOSTS = ("cdn.discordapp.com", "media.discordapp.net")
STYLE = {"approve": 3, "reject": 4}
VOICE_FLAG = 1 << 13


class DiscordError(base.MessengerError):
    def __init__(self, what, code, description):
        super().__init__(f"Discord {what}", code, description, permanent=code in (400, 401, 403, 404))


class Fatal(RuntimeError):
    """다시 붙어도 소용없는 닫힘(토큰·intent 문제)."""


def to_discord(text):
    """마크다운은 Discord 가 거의 그대로 읽는다. ⟦작업용⟧ 아래는 코드 칸으로."""
    top, work = base.work_split(text)
    return top.strip() + ("\n\n-# 작업용\n```\n" + work.replace("```", "'''") + "\n```" if work else "")


class DiscordApi:
    def __init__(self, token, opener=None, sleep=time.sleep, ws_connect=None):
        self.token = token
        self.http = base.Http((token,), opener=opener, sleep=sleep)
        self.sleep = sleep
        self.ws_connect = ws_connect or ws.connect
        self.lock = threading.Lock()

    def call(self, method, path, body=None, files=None):
        headers = {"Authorization": f"Bot {self.token}", "User-Agent": UA}
        if files:
            data, ctype = base.multipart({"payload_json": body or {}}, files)
        elif body is not None:
            data, ctype = json.dumps(body, ensure_ascii=False).encode(), "application/json"
        else:
            data, ctype = None, None
        if ctype:
            headers["Content-Type"] = ctype
        for attempt in range(6):
            status, _hdr, raw = self.http.request(method, API + path, headers, data)
            d = base.loads(raw)
            if status == 429 and attempt < 5:
                self.sleep(float(d.get("retry_after") or 2) + 0.2)
                continue
            if 200 <= status < 300:
                return d
            raise DiscordError(f"{method} {path.split('?')[0]}", status, self.http.mask(d.get("message") or f"HTTP {status}"))
        raise DiscordError(method, 429, "재시도 한도")

    def fetch(self, url):
        u = urllib.parse.urlparse(url)
        if u.scheme != "https" or u.hostname not in FILE_HOSTS:
            raise ConnectionError(f"Discord 파일 주소가 아닙니다: {u.hostname}")
        status, _h, data = self.http.request("GET", url, {"User-Agent": UA}, timeout=60)
        if status != 200:
            raise ConnectionError(f"Discord 파일 받기 실패 HTTP {status}")
        return data


class DiscordMessenger(base.Messenger):
    name, display = "discord", "Discord"

    def __init__(self, api, cfg):
        dc = cfg.get("discord") or {}
        self.api = api
        self.owner = str(dc.get("owner_id") or "") or None
        self.dm = str(dc.get("dm_channel") or "") or None
        self.bot_id = None
        self.topics = {}

    # ----- 보내기 -----
    def channel(self):
        if not self.dm:
            self.dm = str(self.api.call("POST", "/users/@me/channels", {"recipient_id": self.owner})["id"])
        return self.dm

    def components(self, buttons):
        return [{"type": 1, "components": [
            {"type": 2, "style": STYLE.get(v, 2), "label": label[:80], "custom_id": f"b:{i}"}
            for i, (label, v) in enumerate(buttons[:5])]}]

    def send(self, dest, text, buttons=None, reply_to=None, force_reply=False):
        ch = self.channel()
        pieces = base.split_fenced(to_discord(text), LIMIT)
        last = None
        for i, piece in enumerate(pieces):
            body = {"content": piece or "…", "allowed_mentions": {"parse": []}}
            if i == len(pieces) - 1 and buttons:
                body["components"] = self.components(buttons)
            if reply_to and i == 0:
                body["message_reference"] = {"message_id": str(reply_to), "fail_if_not_exists": False}
            last = self.api.call("POST", f"/channels/{ch}/messages", body)
        return int(ch), int(last["id"])

    def send_file(self, dest, path, caption=""):
        p = Path(path)
        if not p.is_file() or p.stat().st_size > SEND_FILE_MAX:
            raise DiscordError("file", 400, "파일이 없거나 10MB 를 넘음")
        ch = self.channel()
        import mimetypes
        body = {"content": to_discord(caption)[:LIMIT] or None, "attachments": [{"id": 0, "filename": p.name}],
                "allowed_mentions": {"parse": []}}
        m = self.api.call("POST", f"/channels/{ch}/messages", body,
                          files=[("files[0]", p.name, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")])
        return int(ch), int(m["id"])

    def edit(self, chat, msg, text, buttons=None):
        self.api.call("PATCH", f"/channels/{chat}/messages/{msg}",
                      {"content": base.split_fenced(to_discord(text), LIMIT)[0],
                       "components": self.components(buttons) if buttons else []})

    def answer(self, event_id, text):
        """버튼 눌림 응답(3초 안). '받았습니다.' 는 받음만(type 6), 그 밖은 누른 사람에게만 보이는 글(type 4, flags 64)."""
        iid, _, token = str(event_id).partition(":")
        if not iid or not token:
            return
        body = {"type": 6} if text == "받았습니다." else {"type": 4, "data": {"content": text[:LIMIT], "flags": 64}}
        try:
            self.api.call("POST", f"/interactions/{iid}/{token}/callback", body)
        except Exception:  # noqa: BLE001  덤
            pass

    def typing(self, dest):
        try:
            self.api.call("POST", f"/channels/{self.channel()}/typing")
        except Exception:  # noqa: BLE001
            pass

    def react(self, chat, msg, on=True):
        try:
            self.api.call("PUT" if on else "DELETE", f"/channels/{chat}/messages/{msg}/reactions/%F0%9F%91%80/@me")
        except Exception:  # noqa: BLE001
            pass

    def download(self, f, dest_dir):
        path = base.unique_path(dest_dir, f.get("name") or "file")
        path.write_bytes(self.api.fetch(f["id"]))
        return path

    # ----- 받기 -----
    def deny(self, d):
        return [{"kind": "answer", "id": f"{d.get('id')}:{d.get('token')}", "text": "권한이 없습니다."}]

    def parse(self, t, d):
        """게이트웨이 사건(t, d) → 데몬 사건 목록."""
        d = d or {}
        if t == "READY":
            self.bot_id = str((d.get("user") or {}).get("id") or "") or None
            return []
        if t == "MESSAGE_CREATE":
            a = d.get("author") or {}
            if d.get("guild_id") or a.get("bot") or (self.bot_id and str(a.get("id")) == self.bot_id):
                return []
            if not self.owner or str(a.get("id")) != self.owner or (self.dm and str(d.get("channel_id")) != self.dm):
                return []
            ref = (d.get("message_reference") or {}).get("message_id")
            ev = {"kind": "message", "chat": int(d["channel_id"]), "msg": int(d["id"]), "topic": None, "topic_name": None,
                  "dm": True, "text": d.get("content") or "", "reply_to": int(ref) if ref else None}
            for f in d.get("attachments") or []:
                ct = str(f.get("content_type") or "")
                voice = bool(int(d.get("flags") or 0) & VOICE_FLAG)
                kind = "voice" if voice else "photo" if ct.startswith("image/") else "audio" if ct.startswith("audio/") else "document"
                ev["file"] = {"kind": kind, "id": f.get("url"), "name": f.get("filename"), "size": f.get("size", 0)}
                break
            return [ev] if ev["text"] or "file" in ev else []
        if t == "INTERACTION_CREATE":
            if d.get("type") != 3:
                return []
            user = d.get("user") or (d.get("member") or {}).get("user") or {}
            if d.get("guild_id") or not self.owner or str(user.get("id")) != self.owner or \
                    (self.dm and str(d.get("channel_id")) != self.dm):
                return self.deny(d)
            prefix, _, idx = str((d.get("data") or {}).get("custom_id") or "").partition(":")
            if prefix != "b" or not idx.isdigit():
                return [{"kind": "answer", "id": f"{d.get('id')}:{d.get('token')}", "text": "지난 버튼입니다."}]
            return [{"kind": "button", "id": f"{d.get('id')}:{d.get('token')}", "chat": int(d["channel_id"]),
                     "msg": int((d.get("message") or {}).get("id")), "index": int(idx)}]
        return []

    def gateway(self):
        return self.api.call("GET", "/gateway/bot")["url"]

    def listen(self, handler, beat, store=None, stop=None, on_dispatch=None):
        """게이트웨이 연결을 지키며 받는다. 한 스레드에서 하트비트까지 한다(recv 가 몇 초마다 돌아옴)."""
        try:
            self.channel()
        except Exception:  # noqa: BLE001
            pass
        session = resume_url = seq = None
        url, down = None, None
        while not (stop and stop()):
            try:
                url = url or self.gateway()
                conn = self.api.ws_connect((resume_url if session else url) + "/?v=10&encoding=json")
            except (ConnectionError, OSError, base.MessengerError) as e:
                if isinstance(e, base.MessengerError) and e.code == 401:
                    raise Fatal("Discord 봇 토큰이 맞지 않습니다(401)") from None
                down = down or time.monotonic()
                if time.monotonic() - down > base.DOWN_LIMIT:
                    raise
                time.sleep(5)
                continue
            try:
                hello = None
                t0 = time.monotonic()
                while hello is None and time.monotonic() - t0 < 30:
                    raw = conn.recv()
                    hello = json.loads(raw) if raw else None
                if not hello or hello.get("op") != 10:
                    raise ws.Closed(None, "Hello 가 오지 않음")
                every = hello["d"]["heartbeat_interval"] / 1000.0
                next_hb, acked = time.monotonic() + every * random.random(), True
                if session:
                    conn.send(json.dumps({"op": 6, "d": {"token": self.api.token, "session_id": session, "seq": seq}}))
                else:
                    conn.send(json.dumps({"op": 2, "d": {"token": self.api.token, "intents": INTENTS,
                                                         "properties": {"os": "jarvis", "browser": "jarvis-hq",
                                                                        "device": "jarvis-hq"}}}))
                down = None
                while not (stop and stop()):
                    beat("poll")
                    if time.monotonic() >= next_hb:
                        if not acked:
                            raise ws.Closed(None, "하트비트 응답 없음")
                        conn.send(json.dumps({"op": 1, "d": seq}))
                        acked, next_hb = False, time.monotonic() + every
                    raw = conn.recv()
                    if raw is None:
                        continue
                    m = json.loads(raw)
                    op = m.get("op")
                    if m.get("s") is not None:
                        seq = m["s"]
                    if op == 0:
                        if m.get("t") == "READY":
                            session = m["d"].get("session_id")
                            resume_url = m["d"].get("resume_gateway_url") or url
                        if on_dispatch:
                            on_dispatch(m.get("t"), m.get("d"))
                        try:
                            for ev in self.parse(m.get("t"), m.get("d")):
                                handler(ev)
                        except Exception:  # noqa: BLE001
                            import logging
                            logging.getLogger("jarvisd").exception("받은 것 처리 실패")
                    elif op == 1:
                        conn.send(json.dumps({"op": 1, "d": seq}))
                    elif op == 11:
                        acked = True
                    elif op == 7:
                        break  # 다시 붙어 이어 받기(RESUME)
                    elif op == 9:
                        if not m.get("d"):
                            session = seq = None
                        time.sleep(1 + random.random() * 4)
                        break
            except ws.Closed as e:
                if e.code in FATAL:
                    raise Fatal(f"Discord 가 연결을 닫았습니다({e.code}). 토큰이나 intent 설정을 확인하세요.") from None
                if e.code in (4007, 4009):
                    session = seq = None
            finally:
                conn.close(4000)

    # ----- 설치 때 -----
    def whoami(self):
        me = self.api.call("GET", "/users/@me")
        return me.get("username") or "?"

    def pair(self, wait=120, say=print):
        say(f"Discord 에서 봇 {self.whoami()} 에게 DM 으로 아무 말이나 보내 주세요(봇이 든 서버에서 봇 이름을 눌러 '메시지'). "
            f"{wait}초 기다립니다.")
        found, end = {}, time.time() + wait

        def grab(t, d):
            a = (d or {}).get("author") or {}
            if t == "MESSAGE_CREATE" and not (d or {}).get("guild_id") and not a.get("bot") and a.get("id"):
                found[str(a["id"])] = a.get("global_name") or a.get("username") or "?"

        keep, self.owner = self.owner, None
        try:
            self.listen(lambda ev: None, lambda part: None, stop=lambda: bool(found) or time.time() > end, on_dispatch=grab)
        finally:
            self.owner = keep
        return [{"id": k, "name": v} for k, v in found.items()]
