"""아침·저녁 요약 재료 모으기 `jarvis brief morning|evening [--since 2026-01-31T18:00]` (AI 없이).

Jarvis 는 이 출력만 보고 요약을 쓴다(스킬 jarvis:morning-evening). 빠진 재료가 있으면 여기에 칸을 더한다.
못 읽은 칸은 '못 읽음: 이유' 로 찍는다(지어내지 않게).
"""

import argparse
import time
from datetime import datetime, timedelta

from . import config, executor, worklog


def since_of(kind, now):
    if kind == "morning":
        return (now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    return now.replace(hour=9, minute=0, second=0, microsecond=0)


def todo_open(paths):
    f = paths.harness / "todo.md"
    try:
        return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip().startswith("- [ ]")]
    except OSError:
        return []


def services(cfg):
    labels = [config.label(cfg, n) for n in ("jarvisd", "executor")]
    try:
        states = config.plat().service_states(labels)
    except Exception as e:  # noqa: BLE001
        return [f"못 읽음: {e}"]
    return [f"{lab} {'등록 안 됨' if st == 'missing' else '꺼짐'}" for lab, (st, _pid) in states.items()
            if st in ("missing", "stopped")]


def collect(kind, paths, since=None, now=None, with_services=True):
    now = now or config.now(paths.cfg)
    since = since or since_of(kind, now)
    out = []

    def sec(title, rows):
        out.append(f"[{title}]")
        out.extend(rows or ["없음"])
        out.append("")

    sec(f"{since:%m-%d %H:%M} 이후 한 일(기록)", worklog.since(since, paths))
    try:
        con = executor.connect(paths)
        try:
            sec("승인·실행 요청(기다리는 것)", executor.pending_text(con).splitlines())
            done = con.execute("select * from requests where updated_at>=? and state in (%s) order by id"
                               % ",".join("?" * len(executor.DONE_STATES)),
                               (since.isoformat(timespec="seconds"), *executor.DONE_STATES)).fetchall()
            sec(f"{since:%m-%d %H:%M} 이후 끝난 실행 요청",
                [f"{executor.tag(r['id'])} {r['target']} {r['state']} · {r['title']}" for r in done])
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        sec("승인·실행 요청", [f"못 읽음: {e}"])
    sec("할 일(.harness/todo.md 의 안 끝난 것)", todo_open(paths))
    if with_services:
        sec("꺼져 있는 비서 서비스", services(paths.cfg))
    if kind == "evening":
        today = now.date()
        mem = []
        for f in sorted(paths.memory.glob("*.md")) if paths.memory.is_dir() else []:
            if datetime.fromtimestamp(f.stat().st_mtime).date() == today:
                mem.append(f"{f.name}: " + " ".join(f.read_text(encoding="utf-8").split())[-300:])
        sec("오늘 memory 에 적힌 것", mem)
        sec("오늘 기록 가운데 실패·멈춤 줄", [ln for ln in worklog.lines(today.isoformat(), paths)
                                       if any(w in ln for w in ("실패", "멈춤", "불확실", "실행 안 함"))])
        old = []
        if paths.work.is_dir():
            for d in sorted(paths.work.iterdir()):
                if d.is_dir() and time.time() - d.stat().st_mtime > 7 * 86400:
                    old.append(f"{d.name} (7일 넘게 안 건드림)")
        sec("치울 만한 작업 폴더", old)
    return "\n".join(out).strip()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jarvis brief")
    ap.add_argument("kind", choices=["morning", "evening"])
    ap.add_argument("--since", default="")
    a = ap.parse_args(argv)
    paths = config.Paths()
    since = None
    if a.since:
        since = datetime.fromisoformat(a.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=config.tz(paths.cfg))
    print(collect(a.kind, paths, since))
    return 0

