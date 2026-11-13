"""메신저 공통: 데몬이 쓰는 모양(Messenger), 긴 글 나누기, 작은 HTTP 도우미.

Messenger 가 갖출 것
- name·display·owner·topics(텔레그램 그룹 토픽, 없으면 {})·max_file·reply_how(수정 메모를 어떻게 달아 달라고 할지)
- send(dest, text, buttons=None, reply_to=None, force_reply=False) → (chat, msg)
    dest: 'dm' 또는 토픽 이름(없으면 DM) 또는 (chat, topic). buttons: [(글, 동작)] → 버튼 값은 순번 'b:0'·'b:1'… 만 싣는다.
    긴 글은 메신저 한도에 맞게 나누고 버튼은 마지막 조각에만.
- send_file(dest, path, caption) · edit(chat, msg, text, buttons=None)(버튼이 없으면 거둠) · answer(누름 id, 글)
- typing(dest) · react(chat, msg, on) · download(file, 폴더) → Path · leave(chat)
- parse(받은 것) → 사건 목록. 대표가 아니면 [] 또는 {'kind': 'answer'}(거절 알림)만.
    사건: message{chat,msg,topic,topic_name,dm,text,reply_to,file?} · button{id,chat,msg,index} · answer{id,text} · leave{chat,title}
- listen(handler, beat, store): 받기를 끝없이 돈다. 받은 사건마다 handler(ev). beat('poll') 를 자주 부른다.
    연결이 2분 넘게 안 되면 예외를 낸다(데몬이 끝나고 서비스 관리자가 다시 띄운다).
- pair(wait) → [{'id', 'name'}]: 봇에게 말을 건 사람 찾기(설치 때) · whoami() → 봇 이름
"""

import json
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

WORK_MARK = "⟦작업용⟧"
MAX_FILE = 20 * 1024 * 1024
DOWN_LIMIT = 120  # 이만큼(초) 연결이 안 되면 데몬을 끝내 다시 뜨게


class MessengerError(Exception):
    def __init__(self, what, code=0, description="", permanent=None):
        super().__init__(f"{what} {code}: {description}")
        self.code, self.description = code, description
        self.permanent = permanent if permanent is not None else code in (400, 403, 404)


def split(text, size):
    """긴 글을 줄 단위로 나눈다. 줄이 없으면 글자 수로."""
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


def split_fenced(text, size):
    """split 과 같되 ``` 코드 울타리 안에서 잘리면 그 조각을 닫고 다음 조각에서 다시 연다(마크다운이 깨지지 않게)."""
    parts, out, open_fence = split(text, size - 8), [], False
    for p in parts:
        if open_fence:
            p = "```\n" + p
        fences = sum(1 for ln in p.split("\n") if ln.strip().startswith("```"))
        open_fence = fences % 2 == 1
        out.append(p + ("\n```" if open_fence else ""))
    return out


def work_split(text):
    text = str(text or "")
    if WORK_MARK in text:
        top, _, work = text.partition(WORK_MARK)
        return top.strip("\n"), work.strip()
    return text.strip("\n"), ""


def safe_name(name, fallback="file"):
    return re.sub(r"[^\w.\-가-힣]", "_", str(name or ""))[:80] or fallback


def unique_path(dest_dir, name):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / safe_name(name)
    if path.exists():
        path = dest_dir / f"{path.stem}_{int(time.time())}{path.suffix}"
    return path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """파일 받기에서 다른 곳으로 넘기지 않는다(인증 머리가 딴 곳으로 새지 않게)."""

    def redirect_request(self, *a, **k):
        return None


class Response(dict):
    """HTTP 응답 몸(JSON)과 머리."""
    status = 200
    headers = {}


def multipart(fields, files):
    """fields: {이름: 값(str·dict)}, files: [(필드, 파일 이름, bytes, 형식)] → (몸, Content-Type)."""
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        if v is None:
            continue
        ctype = ""
        if isinstance(v, (dict, list)):
            v, ctype = json.dumps(v, ensure_ascii=False), "Content-Type: application/json\r\n"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n{ctype}\r\n{v}\r\n'.encode())
    for field, fname, data, ftype in files:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'
                     f"Content-Type: {ftype}\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class Http:
    """urllib 한 겹. opener 를 바꿔 끼워 시험한다. 오류 글에서는 토큰을 가린다."""

    def __init__(self, secrets_to_mask=(), opener=None, sleep=time.sleep, clock=time.monotonic):
        self.mask_words = [s for s in secrets_to_mask if s]
        self.opener = opener or urllib.request.urlopen
        self.sleep, self.clock = sleep, clock

    def mask(self, text):
        text = str(text)
        for w in self.mask_words:
            text = text.replace(w, "***")
        return text

    def request(self, method, url, headers=None, body=None, timeout=30):
        """(상태 코드, 머리 dict, 몸 bytes). 연결 실패는 ConnectionError."""
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with self.opener(req, timeout=timeout) as r:
                return getattr(r, "status", 200), dict(getattr(r, "headers", {}) or {}), r.read()
        except urllib.error.HTTPError as e:
            try:
                data = e.read()
            except OSError:
                data = b""
            return e.code, dict(e.headers or {}), data
        except OSError as e:
            raise ConnectionError(f"{method} 연결 실패: {self.mask(e)}") from None


def loads(data):
    try:
        return json.loads(data or b"{}")
    except ValueError:
        return {}


class Messenger:
    name, display = "base", "메신저"
    topics = {}
    max_file = MAX_FILE
    reply_how = "이 글에 답장으로"

    def typing(self, dest):
        pass

    def react(self, chat, msg, on=True):
        pass

    def leave(self, chat):
        pass

    def answer(self, event_id, text):
        pass
