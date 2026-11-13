"""보낼 글 대기열. Agent·실행기·예약 스크립트는 메신저 토큰이 없다.

대표에게 올릴 글은 여기에 쌓고(queue), jarvisd 가 몇 초마다 메신저에 올린다. 데몬이 꺼져 있으면 쌓여 있다가 다시 뜰 때 나간다.
같은 파일(장부 outbox.db)에 메신저 글 번호 ↔ 버튼 값(posts)과 작은 값 저장(kv)도 둔다.
글 번호는 텔레그램·Discord 는 숫자, Slack 은 글('D…' 채널, 'ts:…')이다. 칸 모양(integer)은 예전 그대로 두고
숫자가 아닌 글은 글 그대로 담는다(SQLite 는 칸마다 값 종류를 따로 둔다).
"""

import json
import sqlite3
from pathlib import Path

from . import config

SCHEMA = """
create table if not exists outbox (
  id integer primary key, at text not null, dest text not null, text text not null,
  file text, posted_at text, error text, attempts integer not null default 0
);
create table if not exists posts (
  chat integer not null, msg integer not null, kind text not null, value text, buttons text,
  ref text, at text not null, primary key (chat, msg)
);
create table if not exists kv (k text primary key, v text not null);
"""
MAX_ATTEMPTS = 5


def connect(paths=None):
    paths = paths or config.Paths()
    db = Path(paths.outbox_db)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("pragma journal_mode=wal")
    con.executescript(SCHEMA)
    return con


def queue(con, dest, text, file=None):
    """dest: 'dm'(대표 DM) 또는 토픽 이름(텔레그램 config telegram.topics 에 없으면 DM 으로 감)."""
    with con:
        cur = con.execute("insert into outbox(at, dest, text, file) values (?,?,?,?)",
                          (config.stamp(), dest or "dm", str(text)[:12000], str(file) if file else None))
    return cur.lastrowid


def due(con, limit=20):
    return con.execute("select * from outbox where posted_at is null order by id limit ?", (limit,)).fetchall()


def done(con, row_id):
    with con:
        con.execute("update outbox set posted_at=?, error=null where id=?", (config.stamp(), row_id))


def failed(con, row_id, error, permanent=False):
    """실패 횟수를 세고, 한도를 넘거나 다시 해도 소용없는 실패면 '실패'로 닫는다. 닫았으면 True."""
    with con:
        con.execute("update outbox set attempts=attempts+1, error=? where id=?", (str(error)[:300], row_id))
        n = con.execute("select attempts from outbox where id=?", (row_id,)).fetchone()[0]
        if permanent or n >= MAX_ATTEMPTS:
            con.execute("update outbox set posted_at='실패' where id=?", (row_id,))
            return True
    return False


def key(v):
    """숫자로 읽히면 숫자(예전 장부와 같게), 아니면 글 그대로."""
    if isinstance(v, int):
        return v
    s = str(v)
    return int(s) if s.lstrip("-").isdigit() else s


def remember_post(con, chat, msg, kind, value=None, buttons=None, ref=None):
    with con:
        con.execute("insert or replace into posts(chat, msg, kind, value, buttons, ref, at) values (?,?,?,?,?,?,?)",
                    (key(chat), key(msg), kind, value, json.dumps(buttons, ensure_ascii=False) if buttons else None,
                     ref, config.stamp()))


def post_of(con, chat, msg):
    return con.execute("select * from posts where chat=? and msg=?", (key(chat), key(msg))).fetchone()


def posts_for(con, kind, value):
    return con.execute("select * from posts where kind=? and value=?", (kind, value)).fetchall()


def clear_buttons(con, chat, msg):
    with con:
        con.execute("update posts set buttons=null where chat=? and msg=?", (key(chat), key(msg)))


def kv_get(con, k, default=None):
    r = con.execute("select v from kv where k=?", (k,)).fetchone()
    return r[0] if r else default


def kv_set(con, k, v):
    with con:
        con.execute("insert or replace into kv(k, v) values (?,?)", (k, str(v)))
