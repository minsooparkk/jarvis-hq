#!/usr/bin/env python3
"""SessionStart 훅: Jarvis 홈에서 시작한 세션(또는 jarvisd 가 띄운 세션)에만 짧은 맥락을 붙인다.

- 지금 시각(설정한 시간대), 승인 기다리는 요청 수, 오늘 한 일 줄 수, 실행기 멈춤 여부
- 규칙이 어디 있는지(CLAUDE.md → RULES.md 색인 → rules/). CLAUDE.md 가 없어졌으면 핵심 규칙 몇 줄을 대신 넣는다.
그 밖의 폴더에서 연 세션에는 아무것도 붙이지 않는다(다른 일에 끼어들지 않음). 표준 라이브러리만 쓴다(맥·윈도).
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

CORE = ("핵심 규칙(CLAUDE.md 가 없어 대신 넣음): 되돌릴 수 있는 일은 묻지 않고 하고 가정은 한 줄로 적는다. "
        "되돌릴 수 없는 일(발송·배포·결제·영구 삭제·공개 게시)은 `jarvis exec request` 승인으로만. "
        "비밀값 원문은 읽지도 적지도 보내지도 않는다. 지우는 대신 휴지통(~/.Trash). /jarvis:doctor 로 홈을 되살린다.")


def pending_counts(db):
    """(승인 대기, 실행 대기). 먼저 읽기 전용으로 연다. WAL 장부는 곁 파일(-wal·-shm)이 없으면 읽기 전용으로 못 여는
    SQLite 판이 있어(파이썬마다 다름), 그때는 일반 연결 + query_only 로 읽는다(곁 파일만 생기고 장부 내용은 안 바뀜)."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
        con.execute("select 1 from requests limit 1").fetchall()
    except sqlite3.OperationalError:
        con = sqlite3.connect(db, timeout=3)
        con.execute("pragma query_only=1")
    try:
        n = con.execute("select count(*) from requests where state='봉인'").fetchone()[0]
        m = con.execute("select count(*) from requests where state in ('승인','실행 중')").fetchone()[0]
        return n, m
    finally:
        con.close()


def inside(path, root):
    """path 가 root 이거나 그 아래인가(윈도는 대소문자·\\ 와 / 를 가리지 않음)."""
    path, root = os.path.normcase(path), os.path.normcase(root)
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def now_in(name):
    """설정한 시간대의 지금. 시간대 자료가 없으면(윈도 기본 파이썬) 이 컴퓨터의 시각."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(name or "Asia/Seoul"))
    except Exception:  # noqa: BLE001
        return datetime.now().astimezone()


def read_stdin():
    """훅 입력(JSON)은 UTF-8 이다. 윈도 콘솔 코드 페이지(cp949 등)로 읽지 않게 바이트로 받아 푼다."""
    data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read()
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data


def utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def main():
    utf8_stdout()
    try:
        event = json.loads(read_stdin())
    except (ValueError, TypeError):
        event = {}
    engine = os.environ.get("JARVIS_HQ_DIR") or os.path.expanduser("~/.jarvis-hq")
    try:
        with open(os.path.join(engine, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return 0
    home = os.path.realpath(os.path.expanduser(str(cfg.get("home") or "~/jarvis")))
    cwd = os.path.realpath(event.get("cwd") or os.getcwd())
    if not (os.environ.get("JARVIS_HQ_AGENT") or inside(cwd, home)):
        return 0
    now = now_in(cfg.get("timezone"))
    lines = [f"지금: {now:%Y-%m-%d %H:%M} ({now:%a})."]
    db = os.path.join(home, ".harness", "ledger", "executor.db")
    if os.path.exists(db):
        try:
            n, m = pending_counts(db)
            lines.append(f"승인 기다리는 요청 {n}건 · 실행 기다리는 요청 {m}건(`jarvis exec pending`).")
        except sqlite3.Error as e:
            lines.append(f"승인 대기 수를 읽지 못함({e}). `jarvis exec pending` 으로 확인한다.")
    log = os.path.join(home, ".harness", "log", f"{now:%Y-%m-%d}.md")
    try:
        with open(log, encoding="utf-8") as f:
            k = sum(1 for ln in f if ln.startswith("- "))
        lines.append(f"오늘 한 일 기록 {k}줄(`jarvis log show`).")
    except OSError:
        lines.append("오늘 한 일 기록은 아직 없음.")
    if os.path.exists(os.path.join(home, ".harness", "state", "executor.pause")):
        lines.append("실행기가 멈춤 상태다(대표가 풀 때까지 승인된 일도 실행되지 않음).")
    if os.path.exists(os.path.join(home, "CLAUDE.md")):
        lines.append("규칙은 CLAUDE.md 가 불러온 것 + RULES.md 색인을 보고 상황에 맞는 rules/ 파일을 읽는다.")
    else:
        lines.append(CORE)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": " ".join(lines)}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
