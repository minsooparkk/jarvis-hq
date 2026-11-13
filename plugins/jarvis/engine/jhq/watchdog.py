"""지킴이. 5분마다 한 번 돈다(맥 launchd <label_prefix>.watchdog, 윈도 작업 스케줄러 같은 이름). AI 없이 돈다.

보는 것: jarvisd·실행기가 서비스로 떠 있는지, jarvisd 심장박동(보내기·받기)과 예약 점검 시각이 멈췄는지.
하는 것: 멈춘 것은 다시 띄우고(맥 launchctl kickstart -k, 윈도 schtasks /End·/Run, jhq.platform), 대표 DM 에
메신저 API 로 직접 알린다(jarvisd 를 거치지 않음). 받기(getUpdates 등)는 하지 않는다(jarvisd 와 부딪침).
같은 문제는 1시간에 한 번, 풀리면 한 번 알린다.
멈춘 것으로 보이는 심장박동은 두 번 연속(4분 넘게 간격) 봤을 때만 문제로 친다(잠깐 느린 것으로 잘 도는 것을 죽이지 않게).
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config, messengers
from . import platform as osplat

STALE, SCHED_STALE, REPEAT, GRACE, CONFIRM = 300, 600, 3600, 300, 240
MISSING = "서비스로 등록돼 있지 않음"


def _age(path, key, now):
    try:
        v = json.loads(Path(path).read_text(encoding="utf-8")).get(key)
        if v is None:
            return None
        return now - (datetime.fromisoformat(v).timestamp() if isinstance(v, str) else float(v))
    except (OSError, ValueError, TypeError):
        return None


def uptime(paths, plat, pid, now):
    """jarvisd 가 뜬 뒤 지난 초. 심장박동 파일의 started(데몬이 뜰 때 적음)를 먼저, 없으면 OS 에 묻는다. 모르면 None."""
    up = _age(paths.heartbeat, "started", now)
    return up if up is not None else plat.process_uptime(pid)


def find_problems(cfg, paths, states, now, uptime=None):
    """states: {라벨: (running|stopped|missing|unknown, pid)}"""
    jarvisd, execd = config.label(cfg, "jarvisd"), config.label(cfg, "executor")
    problems = {}
    for lab in (jarvisd, execd):
        st = (states.get(lab) or ("unknown", None))[0]
        if st == "missing":
            problems[lab] = MISSING
        elif st == "stopped":
            problems[lab] = "떠 있지 않음"
    if jarvisd in problems or (uptime is not None and uptime < GRACE):
        return problems
    flush, poll = _age(paths.heartbeat, "flush", now), _age(paths.heartbeat, "poll", now)
    checked = _age(paths.daemon_state, "checked", now)
    if flush is None or flush > STALE:
        problems[jarvisd] = "심장박동(보내기)이 멈춤" if flush else "심장박동 없음"
    elif poll is not None and poll > STALE:
        problems[jarvisd] = "심장박동(받기)이 멈춤"
    elif checked is not None and checked > SCHED_STALE:
        problems[jarvisd] = "예약 점검이 멈춤"
    return problems


def confirm(problems, suspect, now):
    out = {}
    for lab, why in problems.items():
        if "멈춤" in why or why == "심장박동 없음":
            first = suspect.setdefault(lab, now)
            if now - first < CONFIRM:
                continue
        out[lab] = why
    for lab in list(suspect):
        if lab not in problems:
            suspect.pop(lab)
    return out


def note(cfg, lab, why, ok, msg=""):
    name = {config.label(cfg, "jarvisd"): "Jarvis", config.label(cfg, "executor"): "실행기"}.get(lab, lab)
    if ok is None:
        return (f"🛠 {name} 이(가) 꺼져 있고 서비스 등록이 빠져 있어 다시 켤 수 없습니다.\n"
                f"할 일: 이 컴퓨터에서 Claude Code 를 열고 /jarvis:doctor 를 돌려 주세요.\n\n⟦작업용⟧ {lab}: {why}")
    if ok:
        return f"🛠 {name} 이(가) 멈춰 있어 지킴이가 다시 켰습니다. 멈춘 사이 보내신 말이 있으면 한 번 더 보내 주세요.\n\n⟦작업용⟧ {lab}: {why}"
    return f"🛠 {name} 이(가) 멈춰 있는데 다시 켜지 못했습니다. 5분마다 다시 해 봅니다.\n\n⟦작업용⟧ {lab}: {why} · {msg}"


def run_once(cfg=None, paths=None, run=None, send=None, now=None, plat=None):
    cfg = cfg or config.load()
    paths = paths or config.Paths(cfg)
    plat = plat or (osplat.current(run=run) if run else config.plat())
    now = now or time.time()
    state_f = paths.state / "watchdog.json"
    try:
        st = json.loads(state_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    alerted, suspect = st.get("alerted", {}), st.get("suspect", {})
    if send is None:
        def send(text):
            return messengers.notify_owner(cfg, text)
    labels = [config.label(cfg, "jarvisd"), config.label(cfg, "executor")]
    states = plat.service_states(labels)
    pid = (states.get(labels[0]) or (None, None))[1]
    problems = confirm(find_problems(cfg, paths, states, now, uptime(paths, plat, pid, now)), suspect, now)
    for lab, why in problems.items():
        if why == MISSING:
            text = note(cfg, lab, why, None)
        else:
            ok, msg = plat.service_restart(lab)
            text = note(cfg, lab, why, ok, msg)
            suspect.pop(lab, None)
        if now - alerted.get(lab, 0) >= REPEAT and send(text):
            alerted[lab] = now
    for lab in list(alerted):
        if lab not in problems:
            send("✅ 다시 정상으로 돌아왔습니다: " + lab.rsplit(".", 1)[-1])
            alerted.pop(lab)
    paths.state.mkdir(parents=True, exist_ok=True)
    state_f.write_text(json.dumps({"alerted": alerted, "suspect": suspect, "checked": now}), encoding="utf-8")
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "문제" if problems else "정상", json.dumps(problems, ensure_ascii=False))
    return problems


def main():
    run_once()
    return 0


if __name__ == "__main__":
    sys.exit(main())
