"""텔레그램 Bot API 작은 연결(표준 라이브러리만).

- 대표 DM = 봇과의 1:1 대화(owner_id). 선택: 그룹 하나(group_id)와 토픽 이름 → 번호(topics).
- 들어오는 것은 대표가 DM 이나 우리 그룹에서 보낸 것만 받는다. 다른 사람·다른 방은 버린다(다른 그룹에 초대되면 나옴).
- 버튼(승인·수정·거부)은 callback_data 에 순번만 싣고, 값(봉인 포함)은 장부(outbox.db posts)에 둔다.
- 토큰은 금고에서 데몬이 읽어 이 객체에만 둔다. 오류 글에서는 토큰을 가린다.
- 메신저 층(jhq.messengers)의 텔레그램 구현. 예전 이름 jhq.telegram 으로도 불러 쓸 수 있다.
"""

import html
import json
import mimetypes
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import base

API = "https://api.telegram.org/bot{token}/{method}"
FILE_API = "https://api.telegram.org/file/bot{token}/{path}"
LIMIT = 4096
MAX_FILE = 20 * 1024 * 1024
WORK_MARK = "⟦작업용⟧"


class TgError(base.MessengerError):
    def __init__(self, method, code, description):
        super().__init__(f"Telegram {method}", code, description,
                         permanent=code in (400, 403) and "not modified" not in description)


# ---------- 글 모양 ----------

def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s


def to_html(text):
    """마크다운 조금(**굵게**, `코드`, ``` 울타리, [글](주소))을 텔레그램 HTML 로. ⟦작업용⟧ 아래는 접히는 인용."""
    text = str(text or "")
    top, work = text, ""
    if WORK_MARK in text:
        top, _, work = text.partition(WORK_MARK)
    out, fence = [], None
    for ln in top.strip("\n").split("\n"):
        if ln.strip().startswith("```"):
            if fence is None:
                fence = []
            else:
                out.append("<pre>" + html.escape("\n".join(fence), quote=False) + "</pre>")
                fence = None
            continue
        if fence is not None:
            fence.append(ln)
        else:
            out.append(_inline(re.sub(r"^#{1,6}\s+(.+)$", r"**\1**", ln)))
    if fence:
        out.append("<pre>" + html.escape("\n".join(fence), quote=False) + "</pre>")
    body = "\n".join(out).strip()
    if work.strip():
        body += "\n<blockquote expandable>작업용\n" + html.escape(work.strip(), quote=False) + "</blockquote>"
    return body


def plain_text(text):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or "")).replace(WORK_MARK, "작업용:")


def split(text, size=LIMIT - 300):
    """긴 글을 줄 단위로 나눈다. 작업용 칸이 잘리지 않게 작업용은 마지막 조각에만 둔다."""
    text = str(text or "")
    parts = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        if cut <= 0:
            cut = size
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return parts


# ---------- Bot ----------

class Bot:
    def __init__(self, token, opener=urllib.request.urlopen, sleep=time.sleep, clock=time.monotonic):
        self.token, self.opener, self.sleep, self.clock = token, opener, sleep, clock
        self.lock = threading.Lock()
        self.last = {}

    def mask(self, text):
        return str(text).replace(self.token, "***") if self.token else str(text)

    def _pace(self, chat):
        with self.lock:
            wait = self.last.get(chat, -1e9) + 1.05 - self.clock()
            self.last[chat] = max(self.clock(), self.last.get(chat, -1e9) + 1.05)
        if wait > 0:
            self.sleep(wait)

    def _do(self, req, method, http_timeout):
        try:
            with self.opener(req, timeout=http_timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read())
            except (ValueError, OSError):
                return {"ok": False, "error_code": e.code, "description": "HTTP 오류"}
        except OSError as e:
            raise ConnectionError(f"Telegram {method} 연결 실패: {self.mask(e)}") from None

    def call(self, method, http_timeout=30, **params):
        body = json.dumps({k: v for k, v in params.items() if v is not None}, ensure_ascii=False).encode()
        for attempt in range(6):
            req = urllib.request.Request(API.format(token=self.token, method=method), data=body,
                                         headers={"Content-Type": "application/json"})
            data = self._do(req, method, http_timeout)
            if data.get("ok"):
                return data["result"]
            code, desc = data.get("error_code", 0), self.mask(data.get("description", ""))
            if code == 429 and attempt < 5:
                self.sleep(((data.get("parameters") or {}).get("retry_after") or 3) + 0.5)
                continue
            raise TgError(method, code, desc)
        raise TgError(method, 429, "재시도 한도")

    def upload(self, method, field, path, **params):
        """사진·파일 올리기(multipart)."""
        path = Path(path)
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in params.items():
            if v is None:
                continue
            v = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(API.format(token=self.token, method=method), data=b"".join(parts),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        data = self._do(req, method, 120)
        if data.get("ok"):
            return data["result"]
        raise TgError(method, data.get("error_code", 0), self.mask(data.get("description", "")))

    def download(self, file_id, dest_dir, name=None):
        info = self.call("getFile", file_id=file_id)
        remote = str((info or {}).get("file_path") or "")
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        base = re.sub(r"[^\w.\-가-힣]", "_", name or Path(remote).name or str(file_id))[:80] or "file"
        path = dest_dir / base
        if path.exists():
            path = dest_dir / f"{path.stem}_{int(time.time())}{path.suffix}"
        req = urllib.request.Request(FILE_API.format(token=self.token, path=remote))
        try:
            with self.opener(req, timeout=60) as r, open(path, "wb") as f:
                f.write(r.read())
        except OSError as e:
            if path.exists():
                path.unlink()
            raise ConnectionError(f"Telegram 파일 받기 실패: {self.mask(e)}") from None
        return path


# ---------- 메신저 한 겹 ----------

class TelegramMessenger(base.Messenger):
    """데몬이 쓰는 모양(jhq.messengers.base): send · edit · answer · parse · listen …"""

    name, display = "telegram", "텔레그램"
    max_file = MAX_FILE

    def __init__(self, bot, cfg):
        tg = cfg.get("telegram") or {}
        self.bot = bot
        self.owner = int(tg["owner_id"]) if tg.get("owner_id") else None
        self.group = int(tg["group_id"]) if tg.get("group_id") else None
        self.topics = {str(k): int(v) for k, v in (tg.get("topics") or {}).items()}
        self.topic_names = {v: k for k, v in self.topics.items()}

    def where(self, dest):
        """dest('dm' 또는 토픽 이름) → (chat, topic). 그룹·토픽이 없으면 DM."""
        if dest and dest != "dm" and self.group and dest in self.topics:
            return self.group, self.topics[dest]
        return self.owner, None

    def send(self, dest, text, buttons=None, reply_to=None, force_reply=False):
        """글을 올리고 마지막 조각의 (chat, message_id) 를 돌려준다. buttons: [(글, 순번 값)]."""
        chat, topic = self.where(dest) if not isinstance(dest, tuple) else dest
        markup = None
        if buttons:
            markup = {"inline_keyboard": [[{"text": label, "callback_data": f"b:{i}"} for i, (label, _v) in enumerate(buttons)]]}
        if force_reply:
            markup = {"force_reply": True, "selective": True}
        pieces = split(text)
        last = None
        for i, piece in enumerate(pieces):
            final = i == len(pieces) - 1
            params = {"chat_id": chat, "message_thread_id": topic, "link_preview_options": {"is_disabled": True},
                      "reply_markup": markup if final else None}
            if reply_to and i == 0:
                params["reply_parameters"] = {"message_id": int(reply_to), "allow_sending_without_reply": True}
            self.bot._pace(chat)
            rich = to_html(piece)
            try:
                if len(rich) > LIMIT:
                    raise TgError("sendMessage", 400, "message is too long")
                last = self.bot.call("sendMessage", text=rich, parse_mode="HTML", **params)
            except TgError as e:
                if e.code != 400:
                    raise
                last = self.bot.call("sendMessage", text=plain_text(piece)[:LIMIT], **params)
        return chat, last["message_id"]

    def send_file(self, dest, path, caption=""):
        chat, topic = self.where(dest)
        p = Path(path)
        if not p.is_file() or p.stat().st_size > MAX_FILE:
            raise TgError("sendDocument", 400, "파일이 없거나 20MB 를 넘음")
        photo = p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp")
        self.bot._pace(chat)
        m = self.bot.upload("sendPhoto" if photo else "sendDocument", "photo" if photo else "document", p,
                            chat_id=chat, message_thread_id=topic, caption=plain_text(caption)[:1000] or None)
        return chat, m["message_id"]

    def edit(self, chat, msg, text, buttons=None):
        rows = [[{"text": l, "callback_data": f"b:{i}"} for i, (l, _v) in enumerate(buttons)]] if buttons else []
        markup = {"inline_keyboard": rows}  # 버튼이 없으면 빈 목록 = 버튼 거두기
        try:
            try:
                self.bot.call("editMessageText", chat_id=chat, message_id=int(msg), text=to_html(text)[:LIMIT],
                              parse_mode="HTML", reply_markup=markup)
            except TgError as e:
                if e.code != 400 or "not modified" in e.description:
                    raise
                self.bot.call("editMessageText", chat_id=chat, message_id=int(msg), text=plain_text(text)[:LIMIT],
                              reply_markup=markup)
        except TgError as e:
            if "not modified" not in e.description:
                raise

    def answer(self, callback_id, text):
        try:
            self.bot.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except Exception:  # noqa: BLE001  덤이라 실패해도 처리는 이어 간다
            pass

    def typing(self, dest):
        chat, topic = self.where(dest) if not isinstance(dest, tuple) else dest
        try:
            self.bot.call("sendChatAction", chat_id=chat, action="typing", message_thread_id=topic)
        except Exception:  # noqa: BLE001
            pass

    def react(self, chat, msg, on=True):
        try:
            self.bot.call("setMessageReaction", chat_id=chat, message_id=int(msg),
                          reaction=[{"type": "emoji", "emoji": "👀"}] if on else [])
        except Exception:  # noqa: BLE001
            pass

    def updates(self, offset, timeout=50):
        params = {"timeout": timeout, "allowed_updates": ["message", "callback_query", "my_chat_member"]}
        if offset:
            params["offset"] = offset
        return self.bot.call("getUpdates", http_timeout=timeout + 20, **params)

    def parse(self, u):
        """update 하나 → 데몬이 처리할 사건 목록. 대표·우리 방이 아니면 []."""
        if "my_chat_member" in u:
            mc = u["my_chat_member"]
            chat = mc["chat"]["id"]
            if chat not in (self.owner, self.group) and mc["new_chat_member"]["status"] in ("member", "administrator"):
                return [{"kind": "leave", "chat": chat, "title": mc["chat"].get("title", "")}]
            return []
        if "callback_query" in u:
            q = u["callback_query"]
            m = q.get("message") or {}
            chat = (m.get("chat") or {}).get("id")
            if q["from"]["id"] != self.owner or chat not in (self.owner, self.group):
                return [{"kind": "answer", "id": q["id"], "text": "권한이 없습니다."}]
            prefix, _, idx = str(q.get("data", "")).partition(":")
            if prefix != "b" or not idx.isdigit():
                return [{"kind": "answer", "id": q["id"], "text": "지난 버튼입니다."}]
            return [{"kind": "button", "id": q["id"], "chat": chat, "msg": m.get("message_id"), "index": int(idx)}]
        m = u.get("message")
        if not m:
            return []
        chat, sender = m["chat"]["id"], (m.get("from") or {}).get("id")
        if sender != self.owner or chat not in (self.owner, self.group):
            return []
        if m.get("forum_topic_created") is not None:
            return []
        topic = m.get("message_thread_id") if m.get("is_topic_message") else None
        ev = {"kind": "message", "chat": chat, "msg": m["message_id"], "topic": topic,
              "topic_name": self.topic_names.get(topic) if topic else None,
              "dm": chat == self.owner, "text": m.get("text") or m.get("caption") or "",
              "reply_to": (m.get("reply_to_message") or {}).get("message_id")}
        for kind in ("photo", "document", "voice", "audio", "video"):
            if kind in m:
                f = m[kind][-1] if kind == "photo" else m[kind]
                ev["file"] = {"kind": kind, "id": f["file_id"], "name": f.get("file_name"), "size": f.get("file_size", 0)}
                break
        if not ev["text"] and "file" not in ev:
            return []
        return [ev]

    # ----- 받기·파일·방 -----
    def download(self, f, dest_dir):
        return self.bot.download(f["id"], dest_dir, f.get("name"))

    def leave(self, chat):
        self.bot.call("leaveChat", chat_id=chat)

    def listen(self, handler, beat, store):
        """getUpdates 긴 기다림. store(get/set)에 offset 을 두고, 처리 전에 넘긴다(같은 글을 두 번 처리하지 않는 쪽)."""
        self.bot.call("deleteWebhook", drop_pending_updates=False)
        offset = int(store.get("offset", "0"))
        down = None
        while True:
            beat("poll")
            try:
                ups = self.updates(offset)
                down = None
            except TgError as e:
                if e.code == 401:
                    raise
                down = down or time.monotonic()
                if time.monotonic() - down > base.DOWN_LIMIT:
                    raise
                time.sleep(5)
                continue
            except (OSError, ConnectionError):
                down = down or time.monotonic()
                if time.monotonic() - down > base.DOWN_LIMIT:
                    raise
                time.sleep(5)
                continue
            for u in ups:
                offset = u["update_id"] + 1
                store.set("offset", offset)
                try:
                    for ev in self.parse(u):
                        handler(ev)
                except Exception:  # noqa: BLE001
                    import logging
                    logging.getLogger("jarvisd").exception("받은 것 처리 실패 %s", u.get("update_id"))

    # ----- 설치 때 -----
    def whoami(self):
        return "@" + str((self.bot.call("getMe") or {}).get("username"))

    def pair(self, wait=120, say=print):
        """봇에게 /start 를 보낸 사람(1:1 대화)을 찾는다. 데몬이 돌기 전에만."""
        say(f"봇 {self.whoami()} 에게 텔레그램에서 /start 를 보내 주세요. {wait}초 기다립니다.")
        found, offset, end = {}, None, time.time() + wait
        while time.time() < end and not found:
            ups = self.bot.call("getUpdates", http_timeout=40, timeout=min(25, max(1, int(end - time.time()))),
                                offset=offset, allowed_updates=["message"])
            for u in ups:
                offset = u["update_id"] + 1
                m = u.get("message") or {}
                if (m.get("chat") or {}).get("type") == "private":
                    f = m.get("from") or {}
                    found[f.get("id")] = " ".join(x for x in (f.get("first_name"), f.get("last_name")) if x) \
                        or f.get("username") or "?"
        if offset:
            self.bot.call("getUpdates", offset=offset, timeout=0)  # 읽은 것은 넘긴다(데몬이 다시 처리하지 않게)
        return [{"id": k, "name": v} for k, v in found.items()]


Messenger = TelegramMessenger  # 예전 이름
