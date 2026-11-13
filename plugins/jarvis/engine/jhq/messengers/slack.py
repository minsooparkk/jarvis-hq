"""Slack: Socket Mode(공개 주소가 필요 없음) + Web API. 대표와 봇의 1:1 DM 만 쓴다.

- 토큰 둘: 앱 토큰(xapp-, connections:write)으로 apps.connections.open → 웹소켓 주소, 봇 토큰(xoxb-)으로 글 보내기.
- 받은 봉투(envelope)는 처리 전에 곧바로 envelope_id 로 응답(ack)한다(3초 안. 안 하면 Slack 이 다시 보낸다).
- 받기 거르기: 대표 멤버 ID(owner_id)가 대표 DM 채널(conversations.open 으로 연 D…)에서 보낸 글·버튼만.
  팀 id 를 적어 두었으면(team_id) 다른 워크스페이스 것은 버린다. 봇 자신의 글(bot_id·subtype)은 버린다.
- 버튼: Block Kit 버튼의 action_id·value 는 순번 'b:0'… 만. 값('R-n|봉인')은 장부에 둔다(텔레그램과 같음).
- 글 번호: 채널 'D…' 와 'ts:<ts>'(ts 는 숫자처럼 보여 장부 정수 칸에서 실수로 바뀌지 않게 앞에 ts: 를 붙임).
- 서식: 마크다운 조금 → Slack mrkdwn(*굵게*, <주소|글>, &·<·> 이스케이프). 글은 3500자씩, 버튼 글의 칸은 2900자씩.
- 공식 문서(docs.slack.dev, 2026-11-13 읽음): Socket Mode, message.im, block_actions, chat.postMessage·update,
  conversations.open, files.getUploadURLExternal·completeUploadExternal(files.upload 는 2025-11-12 종료), 429 Retry-After.
  실제 Slack 에 붙여 본 적은 없다(토큰 없음). 점검표: docs/메신저-확인할-것.md
"""

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import base, ws

API = "https://slack.com/api/"
TEXT_LIMIT, BLOCK_LIMIT = 3500, 2900
FILE_HOSTS = ("files.slack.com",)
STYLE = {"approve": "primary", "reject": "danger"}


class SlackError(base.MessengerError):
    def __init__(self, method, error):
        super().__init__(f"Slack {method}", 400, error,
                         permanent=error not in ("ratelimited", "internal_error", "fatal_error", "service_unavailable"))


def to_mrkdwn(text):
    """마크다운 조금(**굵게**, # 제목, [글](주소), `코드`, ``` 울타리) → Slack mrkdwn. ⟦작업용⟧ 아래는 코드 칸으로."""
    top, work = base.work_split(text)
    out, fence = [], False
    for ln in top.split("\n"):
        if ln.strip().startswith("```"):
            fence = not fence
            out.append(ln)
            continue
        ln = ln.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if fence:
            out.append(ln)
            continue
        ln = re.sub(r"^#{1,6}\s+(.+)$", r"**\1**", ln)
        ln = re.sub(r"\*\*(.+?)\*\*", r"*\1*", ln)
        ln = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", ln)
        out.append(ln)
    body = "\n".join(out).strip()
    if work:
        w = work.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("```", "'''")
        body += "\n\n_작업용_\n```\n" + w + "\n```"
    return body


def unescape(text):
    return str(text or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


class SlackApi:
    def __init__(self, bot_token, app_token, opener=None, sleep=time.sleep, ws_connect=None):
        self.bot_token, self.app_token = bot_token, app_token
        self.http = base.Http((bot_token, app_token), opener=opener, sleep=sleep)
        # 파일 받기는 넘겨주기(redirect)를 따라가지 않는 opener 로(시험은 같은 가짜 opener)
        self.fetch_http = base.Http((bot_token,), opener=opener or urllib.request.build_opener(base.NoRedirect).open)
        self.sleep = sleep
        self.ws_connect = ws_connect or ws.connect
        self.lock = threading.Lock()
        self.last = {}

    def call(self, method, token=None, form=False, **params):
        params = {k: v for k, v in params.items() if v is not None}
        headers = {"Authorization": f"Bearer {token or self.bot_token}"}
        if form:
            body = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                           for k, v in params.items()}).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(params, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json; charset=utf-8"
        for attempt in range(6):
            status, hdr, data = self.http.request("POST", API + method, headers, body)
            if status == 429 and attempt < 5:
                self.sleep(float({k.lower(): v for k, v in hdr.items()}.get("retry-after") or 3) + 0.5)
                continue
            d = base.loads(data)
            if d.get("ok"):
                return d
            raise SlackError(method, self.http.mask(d.get("error") or f"HTTP {status}"))
        raise SlackError(method, "ratelimited")

    def pace(self, chat):
        with self.lock:
            wait = self.last.get(chat, -1e9) + 1.05 - time.monotonic()
            self.last[chat] = max(time.monotonic(), self.last.get(chat, -1e9) + 1.05)
        if wait > 0:
            self.sleep(wait)

    def socket_url(self):
        return self.call("apps.connections.open", token=self.app_token, form=True)["url"]

    def fetch(self, url):
        """대표가 보낸 파일 받기. files.slack.com 의 https 주소만, 넘겨주기(redirect)는 따라가지 않는다."""
        u = urllib.parse.urlparse(url)
        if u.scheme != "https" or u.hostname not in FILE_HOSTS:
            raise ConnectionError(f"Slack 파일 주소가 아닙니다: {u.hostname}")
        status, _h, data = self.fetch_http.request("GET", url, {"Authorization": f"Bearer {self.bot_token}"}, timeout=60)
        if status != 200:
            raise ConnectionError(f"Slack 파일 받기 실패 HTTP {status}")
        return data

    def upload(self, url, data):
        status, _h, _d = self.http.request("POST", url, {"Content-Type": "application/octet-stream"}, data, timeout=120)
        if status != 200:
            raise SlackError("upload", f"HTTP {status}")


class SlackMessenger(base.Messenger):
    name, display = "slack", "Slack"
    reply_how = "이 글의 스레드에 답장으로"

    def __init__(self, api, cfg):
        sc = cfg.get("slack") or {}
        self.api = api
        self.owner = str(sc.get("owner_id") or "") or None
        self.team = sc.get("team_id") or None
        self.dm = sc.get("dm_channel") or None
        self.topics = {}
        self.seen = []  # 이미 처리한 사건(다시 보낸 것 거르기)

    # ----- 보내기 -----
    def channel(self):
        if not self.dm:
            self.dm = self.api.call("conversations.open", users=self.owner)["channel"]["id"]
        return self.dm

    def buttons_block(self, buttons):
        return {"type": "actions", "elements": [
            dict({"type": "button", "text": {"type": "plain_text", "text": label[:75]}, "action_id": f"b:{i}",
                  "value": f"b:{i}"}, **({"style": STYLE[v]} if v in STYLE else {}))
            for i, (label, v) in enumerate(buttons)]}

    def blocks(self, text, buttons):
        secs = [{"type": "section", "text": {"type": "mrkdwn", "text": p}} for p in base.split_fenced(text, BLOCK_LIMIT) if p.strip()]
        return secs[:49] + ([self.buttons_block(buttons)] if buttons else [])

    def send(self, dest, text, buttons=None, reply_to=None, force_reply=False):
        ch = self.channel()
        pieces = base.split_fenced(to_mrkdwn(text), TEXT_LIMIT)
        last = None
        for i, piece in enumerate(pieces):
            final = i == len(pieces) - 1
            self.api.pace(ch)
            params = {"channel": ch, "text": piece, "unfurl_links": False, "unfurl_media": False}
            if final and buttons:
                params["blocks"] = self.blocks(piece, buttons)
            last = self.api.call("chat.postMessage", **params)
        return ch, "ts:" + str(last["ts"])

    def send_file(self, dest, path, caption=""):
        p = Path(path)
        if not p.is_file() or p.stat().st_size > self.max_file:
            raise SlackError("files.upload", "파일이 없거나 20MB 를 넘음")
        data = p.read_bytes()
        up = self.api.call("files.getUploadURLExternal", form=True, filename=p.name, length=len(data))
        self.api.upload(up["upload_url"], data)
        ch = self.channel()
        self.api.call("files.completeUploadExternal", files=[{"id": up["file_id"], "title": p.name}], channel_id=ch,
                      initial_comment=to_mrkdwn(caption)[:1000] or None)
        return ch, "file:" + up["file_id"]

    def edit(self, chat, msg, text, buttons=None):
        body = to_mrkdwn(text)[:TEXT_LIMIT]
        self.api.call("chat.update", channel=chat, ts=str(msg)[3:], text=body,
                      blocks=self.blocks(body, buttons) if buttons else [])

    def answer(self, event_id, text):
        """Slack 은 봉투 응답(ack)을 받을 때 이미 했다. 알릴 말이 있으면 DM 한 줄."""
        if text and text != "받았습니다.":
            try:
                self.send("dm", text)
            except Exception:  # noqa: BLE001
                pass

    def react(self, chat, msg, on=True):
        try:
            self.api.call("reactions.add" if on else "reactions.remove", channel=chat, timestamp=str(msg)[3:], name="eyes")
        except Exception:  # noqa: BLE001  덤
            pass

    def download(self, f, dest_dir):
        path = base.unique_path(dest_dir, f.get("name") or "file")
        path.write_bytes(self.api.fetch(f["id"]))
        return path

    # ----- 받기 -----
    def _dup(self, key):
        if not key:
            return False
        if key in self.seen:
            return True
        self.seen = (self.seen + [key])[-500:]
        return False

    def parse(self, env):
        """봉투 하나 → 사건 목록."""
        t, p = env.get("type"), env.get("payload") or {}
        if self.team and p.get("team_id", (p.get("team") or {}).get("id", self.team)) != self.team:
            return []
        if t == "events_api":
            e = p.get("event") or {}
            if e.get("type") != "message" or e.get("channel_type") != "im":
                return []
            if e.get("bot_id") or e.get("subtype") not in (None, "file_share") or e.get("hidden"):
                return []
            if not self.owner or e.get("user") != self.owner or (self.dm and e.get("channel") != self.dm):
                return []
            if self._dup(p.get("event_id") or e.get("ts")):
                return []
            thread = e.get("thread_ts")
            ev = {"kind": "message", "chat": e.get("channel"), "msg": "ts:" + str(e.get("ts")), "topic": None,
                  "topic_name": None, "dm": True, "text": unescape(e.get("text")),
                  "reply_to": "ts:" + str(thread) if thread and thread != e.get("ts") else None}
            for f in e.get("files") or []:
                if f.get("mode") == "external" or f.get("is_external") or not f.get("url_private_download"):
                    continue
                mt = str(f.get("mimetype") or "")
                kind = "photo" if mt.startswith("image/") else "audio" if mt.startswith("audio/") else "document"
                ev["file"] = {"kind": kind, "id": f["url_private_download"], "name": f.get("name"), "size": f.get("size", 0)}
                break
            return [ev] if ev["text"] or "file" in ev else []
        if t == "interactive":
            if p.get("type") != "block_actions":
                return []
            user = (p.get("user") or {}).get("id")
            cont = p.get("container") or {}
            chat = (p.get("channel") or {}).get("id") or cont.get("channel_id")
            if not self.owner or user != self.owner or (self.dm and chat != self.dm):
                return []  # 대표 DM 밖·다른 사람의 눌림은 버린다(승인 안 됨)
            acts = p.get("actions") or [{}]
            prefix, _, idx = str(acts[0].get("value") or acts[0].get("action_id") or "").partition(":")
            if prefix != "b" or not idx.isdigit() or self._dup(f"{cont.get('message_ts')}|{acts[0].get('action_ts')}"):
                return []
            return [{"kind": "button", "id": p.get("trigger_id") or "", "chat": chat, "msg": "ts:" + str(cont.get("message_ts")),
                     "index": int(idx)}]
        return []

    def listen(self, handler, beat, store=None, stop=None):
        try:
            self.channel()  # 대표 DM 채널을 알아 두면 그 채널 밖의 것은 버린다
        except Exception:  # noqa: BLE001
            pass
        down = None
        while not (stop and stop()):
            try:
                conn = self.api.ws_connect(self.api.socket_url())
            except (ConnectionError, OSError, SlackError) as e:
                if isinstance(e, SlackError) and e.description in ("invalid_auth", "not_authed", "account_inactive"):
                    raise
                down = down or time.monotonic()
                if time.monotonic() - down > base.DOWN_LIMIT:
                    raise
                time.sleep(5)
                continue
            down = None
            try:
                while not (stop and stop()):
                    beat("poll")
                    raw = conn.recv()
                    if raw is None:
                        continue
                    env = json.loads(raw)
                    if env.get("envelope_id"):
                        conn.send(json.dumps({"envelope_id": env["envelope_id"]}))
                    if env.get("type") == "disconnect":
                        break
                    try:
                        for ev in self.parse(env):
                            handler(ev)
                    except Exception:  # noqa: BLE001
                        import logging
                        logging.getLogger("jarvisd").exception("받은 것 처리 실패")
            except ws.Closed:
                pass
            finally:
                conn.close()

    # ----- 설치 때 -----
    def whoami(self):
        a = self.api.call("auth.test")
        self.team = self.team or a.get("team_id")
        return f"{a.get('user')} ({a.get('team')})"

    def pair(self, wait=120, say=print):
        """봇에게 DM 을 보낸 사람을 찾는다(데몬이 돌기 전에만)."""
        say(f"Slack 에서 앱 {self.whoami()} 에게 DM 으로 아무 말이나 보내 주세요. {wait}초 기다립니다.")
        found, end = {}, time.time() + wait
        keep_owner, self.owner, self.dm = self.owner, None, None

        def grab(env):
            e = (env.get("payload") or {}).get("event") or {}
            if env.get("type") == "events_api" and e.get("channel_type") == "im" and not e.get("bot_id") and e.get("user"):
                found[e["user"]] = e["user"]

        conn = self.api.ws_connect(self.api.socket_url())
        try:
            while time.time() < end and not found:
                raw = conn.recv()
                if raw:
                    env = json.loads(raw)
                    if env.get("envelope_id"):
                        conn.send(json.dumps({"envelope_id": env["envelope_id"]}))
                    grab(env)
        finally:
            conn.close()
            self.owner = keep_owner
        out = []
        for uid in found:
            try:
                u = self.api.call("users.info", form=True, user=uid)["user"]
                name = (u.get("profile") or {}).get("real_name") or u.get("name") or uid
            except Exception:  # noqa: BLE001
                name = uid
            out.append({"id": uid, "name": name})
        return out
