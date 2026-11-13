"""한 일 기록. 날짜별 파일 <홈>/.harness/log/YYYY-MM-DD.md 에 한 줄씩 더하기만 한다(고치거나 지우지 않음).

한 줄: `- HH:MM · 누가 · 무엇을 · 결과 · 근거`
실행기·jarvisd·Jarvis 가 같이 쓰므로 파일 잠금(맥 flock · 윈도 msvcrt, jhq.platform) 아래 한 줄씩 쓴다.

  jarvis log add "무엇을" --결과 "완료" [--근거 "경로·R-0001"] [--누가 Jarvis]
  jarvis log show [--date 2026-01-31] [--days 2]
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

from . import config


def _clean(s, n=400):
    s = " ".join(str(s or "").split()).replace(" · ", " / ")
    return s if len(s) <= n else s[:n - 1] + "…"


def path_for(day, paths=None):
    paths = paths or config.Paths()
    return paths.log / f"{day}.md"


def add(what, result="", evidence="", who="Jarvis", at=None, paths=None):
    """한 줄 더한다. 실패해도 부른 쪽 일을 멈추지 않게 예외 대신 False."""
    paths = paths or config.Paths()
    at = at or config.now(paths.cfg)
    line = f"- {at:%H:%M} · {_clean(who, 40)} · {_clean(what)} · {_clean(result, 200) or '-'} · {_clean(evidence, 300) or '-'}\n"
    try:
        paths.log.mkdir(parents=True, exist_ok=True)
        f = path_for(at.strftime("%Y-%m-%d"), paths)
        plat = config.plat()
        with open(f, "a", encoding="utf-8") as h:
            plat.lock(h)
            try:
                if os.fstat(h.fileno()).st_size == 0:
                    h.write(f"# 한 일 기록 {at:%Y-%m-%d}\n\n")
                h.write(line)
            finally:
                plat.unlock(h)
        return True
    except OSError as e:
        print(f"한 일 기록 실패: {e}", file=sys.stderr)
        return False


def lines(day, paths=None):
    try:
        text = path_for(day, paths).read_text(encoding="utf-8")
    except OSError:
        return []
    return [ln for ln in text.splitlines() if ln.startswith("- ")]


def since(t, paths=None):
    """시각 t 이후의 줄들(날짜를 붙여)."""
    paths = paths or config.Paths()
    out, day, end = [], t.date(), config.now(paths.cfg).date()
    while day <= end:
        for ln in lines(day.isoformat(), paths):
            if day > t.date() or ln[2:7] >= f"{t:%H:%M}":
                out.append(f"{day:%m-%d} {ln[2:]}")
        day += timedelta(days=1)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jarvis log", description="한 일 기록(.harness/log/날짜.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_ = sub.add_parser("add", help="한 줄 더하기")
    a_.add_argument("what")
    a_.add_argument("--결과", "--result", dest="result", default="")
    a_.add_argument("--근거", "--evidence", dest="evidence", default="")
    a_.add_argument("--누가", "--who", dest="who", default="Jarvis")
    s = sub.add_parser("show", help="보기")
    s.add_argument("--date", default="")
    s.add_argument("--days", type=int, default=1)
    a = ap.parse_args(argv)
    paths = config.Paths()
    if a.cmd == "add":
        ok = add(a.what, a.result, a.evidence, a.who, paths=paths)
        print("적었습니다." if ok else "못 적었습니다.")
        return 0 if ok else 1
    end = datetime.fromisoformat(a.date).date() if a.date else config.now(paths.cfg).date()
    for i in range(max(1, a.days) - 1, -1, -1):
        day = (end - timedelta(days=i)).isoformat()
        got = lines(day, paths)
        print(f"[{day}] {len(got)}줄")
        print("\n".join(got) or "없음")
    return 0
