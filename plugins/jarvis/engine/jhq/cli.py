"""`jarvis` 명령 하나로 엔진을 부른다.

  jarvis exec …        실행 요청(승인)·상태          jarvis log …       한 일 기록
  jarvis notify …      대표에게 알림(보낼 글 대기열)   jarvis perms …     권한 빌드
  jarvis secret …      비밀값 넣기·목록(대표 터미널)   jarvis messenger … 봇 연결(pair·set-owner·test·status)
                                                       (jarvis telegram … 은 예전 이름: 텔레그램으로 messenger)
  jarvis status        데몬·승인·심장박동              jarvis stt …       받아쓰기(선택 모듈)
  jarvis mail …        Gmail 보내기 요청(선택 모듈)    jarvis brief …     아침·저녁 요약 재료
  jarvis version
"""

import argparse
import getpass
import json
import sys
import time

from . import config, executor, messengers, outbox, perms, secrets, worklog


def cmd_notify(argv):
    ap = argparse.ArgumentParser(prog="jarvis notify", description="대표에게 알림(jarvisd 가 몇 초 안에 올림)")
    ap.add_argument("dest", help="dm 또는 토픽 이름")
    ap.add_argument("text")
    ap.add_argument("--file", help="함께 올릴 그림·파일(Jarvis 홈 아래만)")
    ap.add_argument("--once", help="이 열쇠로 최근에 보냈으면 건너뜀")
    ap.add_argument("--hours", type=float, default=6)
    a = ap.parse_args(argv)
    paths = config.Paths()
    f = None
    if a.file:
        from pathlib import Path
        f = Path(a.file).expanduser().resolve()
        if not f.is_file():
            print(f"파일이 없습니다: {f}", file=sys.stderr)
            return 1
        if paths.home.resolve() not in f.parents:
            print("Jarvis 홈 아래 파일만 올립니다(다른 곳은 먼저 홈 아래로 복사).", file=sys.stderr)
            return 1
    con = outbox.connect(paths)
    try:
        if a.once:
            last = float(outbox.kv_get(con, f"once:{a.once}", "0"))
            if time.time() - last < a.hours * 3600:
                print("건너뜀(최근에 같은 알림을 보냄)")
                return 0
        outbox.queue(con, a.dest, a.text, file=f)
        if a.once:
            outbox.kv_set(con, f"once:{a.once}", time.time())
    finally:
        con.close()
    print("넣었습니다.")
    return 0


def cmd_secret(argv):
    ap = argparse.ArgumentParser(prog="jarvis secret", description="비밀값(맥 키체인·윈도 자격 증명 관리자). 값은 화면에 나오지 않는다.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set", help="값 넣기(대표가 자기 터미널에서. 입력은 화면에 안 보임)")
    s.add_argument("name", help="telegram · slack-bot · slack-app · discord, 또는 다른 이름(예: gmail-client-secret)")
    sub.add_parser("list", help="있는지만 보기")
    sub.add_parser("ensure-seal", help=argparse.SUPPRESS)
    d = sub.add_parser("delete", help="지우기(대표 몫)")
    d.add_argument("name")
    a = ap.parse_args(argv)
    cfg = config.load()
    if a.cmd == "list":
        known = list(secrets.KNOWN) + [n for n in messengers.spec(cfg)["secrets"] if n not in secrets.KNOWN]
        names = known + [n for n in cfg.get("secret_names", []) if n not in known]
        for n in names:
            print(f"{n}: {'있음' if secrets.has(n, cfg) else '없음'}")
        return 0
    if a.cmd == "delete":
        print("지웠습니다." if secrets.delete(a.name, cfg) else "없었습니다.")
        return 0
    if a.cmd == "ensure-seal":
        print("서명 열쇠를 만들었습니다." if secrets.ensure_seal_key(cfg) else "서명 열쇠가 이미 있습니다.")
        return 0
    if not sys.stdin.isatty():
        print("이 명령은 대표가 자기 터미널에서 직접 돌립니다(값을 채팅에 붙여 넣지 않습니다).", file=sys.stderr)
        return 2
    name = secrets.ALIASES.get(a.name, a.name)
    value = getpass.getpass(f"{name} 값을 붙여 넣고 Enter (화면에 안 보입니다): ").strip()
    if not value:
        print("빈 값이라 넣지 않았습니다.", file=sys.stderr)
        return 1
    bad = messengers.check_secret(name, value)
    if bad:
        print(bad, file=sys.stderr)
        return 1
    secrets.put(name, value, cfg)
    builtin = [n for sp in messengers.SPECS.values() for n in sp["secrets"]] + list(secrets.KNOWN)
    if name not in builtin and name not in cfg.get("secret_names", []):
        cfg.setdefault("secret_names", []).append(name)
        config.save(cfg)
    print(f"{name} 을(를) 금고({config.plat().vault_word})에 넣었습니다. 값은 어디에도 찍히지 않았습니다.")
    return 0


def cmd_messenger(argv, name=None):
    """메신저 연결: pair(봇에게 말 건 사람 찾기) · set-owner(대표 id 적기) · test(시험 글) · status."""
    cfg = config.load()
    prog = f"jarvis {name}" if name else "jarvis messenger"
    ap = argparse.ArgumentParser(prog=prog)
    if not name:
        ap.add_argument("--messenger", choices=messengers.NAMES, help="설정과 다른 메신저를 볼 때")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair", help="봇에게 온 메시지에서 보낸 사람(id)을 찾는다. 데몬이 돌기 전에만.")
    p.add_argument("--wait", type=int, default=120)
    o = sub.add_parser("set-owner", help="대표 id 를 설정에 적는다(텔레그램 chat id · Slack 멤버 ID · Discord 사용자 ID)")
    o.add_argument("owner_id")
    sub.add_parser("test", help="대표 DM 에 시험 글 하나 보내기")
    sub.add_parser("status", help="메신저 설정이 다 됐는지")
    a = ap.parse_args(argv)
    m = name or getattr(a, "messenger", None) or messengers.kind(cfg)
    sp = messengers.SPECS[m]
    if a.cmd == "status":
        gone = messengers.missing(cfg, m)
        print(f"메신저: {sp['display']}" + (" (설정의 메신저)" if m == messengers.kind(cfg) else ""))
        print("준비됨" if not gone else "모자람: " + ", ".join(gone))
        return 0 if not gone else 1
    if a.cmd == "set-owner":
        try:
            v = messengers.set_owner(cfg, a.owner_id, m)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        config.save(cfg)
        print(f"대표 {sp['owner_word']} 를 적었습니다: {v}")
        return 0
    try:
        msgr = messengers.connect(cfg, m)
    except messengers.NotReady as e:
        print(str(e), file=sys.stderr)
        return 2
    if a.cmd == "test":
        if not messengers.owner(cfg, m):
            print(f"대표 {sp['owner_word']} 가 없습니다(jarvis messenger pair → set-owner).", file=sys.stderr)
            return 2
        msgr.send("dm", "연결 시험입니다. 이 글이 보이면 봇 연결이 된 것입니다.")
        print("보냈습니다.")
        return 0
    found = msgr.pair(a.wait, say=lambda t: print(t, flush=True))
    if not found:
        print("받은 메시지가 없습니다. 봇에게 말을 건 뒤 다시 돌리세요.", file=sys.stderr)
        return 1
    print(json.dumps([{"owner_id": f["id"], "name": f["name"]} for f in found], ensure_ascii=False))
    print(f"보낸 사람이 본인이 맞으면: jarvis {name or 'messenger'} set-owner <owner_id>")
    return 0


def status(paths):
    cfg = paths.cfg
    now = time.time()

    def age(key):
        try:
            return round(now - float(json.loads(paths.heartbeat.read_text(encoding="utf-8")).get(key)))
        except (OSError, ValueError, TypeError):
            return None
    try:
        st = json.loads(paths.daemon_state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    out = {"version": config.VERSION, "home": str(paths.home), "engine": str(config.engine_dir()),
           "messenger": cfg.get("messenger") or "telegram", "owner_id_set": bool(messengers.owner(cfg)),
           "heartbeat_flush_sec": age("flush"), "heartbeat_poll_sec": age("poll"),
           "schedule_checked": st.get("checked"), "last_reply_at": st.get("last_reply_at"),
           "executor_paused": paths.pause.exists()}
    try:
        con = executor.connect(paths)
        try:
            out["pending_approvals"] = len(executor.pending_approvals(con))
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        out["pending_approvals"] = f"확인 실패: {e}"
    return out


def cmd_status(argv):
    ap = argparse.ArgumentParser(prog="jarvis status")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--wait-reply", type=int, default=0, help="이 초 동안 jarvisd 가 새 답을 올리는지 기다림(설치 확인용)")
    a = ap.parse_args(argv)
    paths = config.Paths()
    s = status(paths)
    if a.wait_reply:
        start, end = s.get("last_reply_at"), time.time() + a.wait_reply
        while time.time() < end:
            s = status(paths)
            if s.get("last_reply_at") and s["last_reply_at"] != start:
                break
            time.sleep(3)
        s["replied"] = bool(s.get("last_reply_at") and s["last_reply_at"] != start)
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
    else:
        for k, v in s.items():
            print(f"{k}: {v}")
    return 0 if not a.wait_reply or s.get("replied") else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "exec":
        return executor.main(rest)
    if cmd == "log":
        return worklog.main(rest)
    if cmd == "perms":
        return perms.main(rest)
    if cmd == "notify":
        return cmd_notify(rest)
    if cmd == "secret":
        return cmd_secret(rest)
    if cmd == "messenger":
        return cmd_messenger(rest)
    if cmd in ("telegram", "slack", "discord"):
        return cmd_messenger(rest, name=cmd)
    if cmd == "status":
        return cmd_status(rest)
    if cmd == "brief":
        from . import brief
        return brief.main(rest)
    if cmd == "stt":
        from .extras import stt
        return stt.main(rest)
    if cmd == "mail":
        from .extras import gmail
        return gmail.main(rest)
    if cmd == "version":
        print(config.VERSION)
        return 0
    print(f"모르는 명령: {cmd}\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

