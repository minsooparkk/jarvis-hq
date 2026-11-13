"""실행기. 대표가 승인한 그대로만, 한 번만 실행한다.

흐름
1. Jarvis 가 `jarvis exec request --target 대상 …` 로 실행 요청을 만든다. 실행기 코드가 내용을 봉인(sha256)한다.
   봉인에는 대상의 실행 방법(hooks/targets.yaml 의 그 대상 전체), 넘기는 입력 파일의 해시, 저장소 대상이면 커밋의 파일 해시가 들어간다.
   요청 자체가 승인 요청이다(R-n, 메신저에는 #요청n). 같은 봉인의 요청이 이미 기다리면 새로 만들지 않는다.
2. jarvisd 가 대표 DM 에 승인 글과 버튼(승인·수정·거부)을 올린다. 미리보기는 Agent 의 설명이 아니라 봉인된 내용에서 만든다.
3. 대표가 '승인'을 누르면 jarvisd 가 화면에 보였던 봉인 값과 지금 다시 계산한 봉인이 같은지 보고, 같을 때만
   서명(HMAC, 금고의 seal-key)한다. Agent 는 서명 열쇠가 없다.
4. 실행기 데몬이 서명을 확인하고, 실행 직전에 봉인을 다시 계산해 같을 때만 실행한다. 다르면 실행하지 않고 알린다.
5. 한 번만: 실행 전에 시도 표시 파일을 O_EXCL 로 만들고 상태를 '실행 중'으로 먼저 적는다. 실행 도중 실행기가 죽으면
   다시 하지 않고 '불확실'로 알린다. 실패해도 저절로 다시 하지 않는다(다시 하려면 새 승인).
6. 멈추기: <홈>/.harness/state/executor.pause 파일이 있으면 아무것도 실행하지 않는다.
"""

import argparse
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import yaml

from . import config, outbox, plain, secrets, worklog

WAITING = ("봉인", "승인")
DONE_STATES = ("완료", "실패", "불확실", "실행 안 함", "거부", "수정 요청")
INPUT_MAX = 5 * 1024 * 1024
SCHEMA = """
create table if not exists requests (
  id integer primary key, kind text not null default 'run', target text not null,
  payload text not null, seal text not null,
  created_at text not null, created_by text not null,
  state text not null default '봉인',
  approval_sig text, approved_at text, note text, result text, updated_at text,
  title text, plain text, if_rejected text, decision_note text
);
"""
KEYMAP = {"이름": "name", "실행": "run", "확인": "check", "창": "window", "저장소": "repo", "브랜치": "branch",
          "경로": "paths", "입력": "input", "시간제한": "timeout_min", "설명": "about"}
INPUT_WORDS = {"필수": "required", "선택": "optional", "없음": "none"}
PLAIN_FIELDS = (("결론", "summary", "한 줄 결론: 무엇을 승인하는지, 승인하면 언제 무엇이 일어나는지", 300),
                ("배경", "why", "왜 하는지, 대표가 한 말 원문", 800),
                ("본문", "details", "대표 눈에 보이는 변화, 되돌리는 법", 1000))


class ExecError(Exception):
    """대표·Jarvis 가 읽는 이유를 담은 오류."""


def rid(n):
    return f"R-{int(n):04d}"


def tag(n):
    return f"#요청{int(n)}"


def parse_rid(s):
    t = str(s).strip().lstrip("#").replace(" ", "").upper()
    for p in ("R-", "R", "요청"):
        t = t.replace(p, "", 1) if t.startswith(p) else t
    if not t.isdigit():
        raise ExecError(f"요청 번호가 이상합니다: {s}")
    return int(t)


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def connect(paths=None):
    paths = paths or config.Paths()
    paths.ledger.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(paths.executor_db, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("pragma journal_mode=wal")
    con.executescript(SCHEMA)
    return con


# ---------- 대상 ----------

def _norm(t):
    out = {}
    for k, v in (t or {}).items():
        out[KEYMAP.get(k, k)] = v
    if isinstance(out.get("run"), str):
        out["run"] = [out["run"]]
    out["input"] = INPUT_WORDS.get(str(out.get("input") or "none"), str(out.get("input") or "none"))
    out["window"] = str(out.get("window") or "always")
    return out


def load_targets(paths):
    try:
        doc = yaml.safe_load(Path(paths.targets).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    raw = doc.get("대상") or doc.get("targets") or {}
    return {str(k): _norm(v) for k, v in raw.items()}


def target_cfg(paths, name):
    t = load_targets(paths).get(name)
    if not t:
        raise ExecError(f"실행 대상이 아닙니다: {name} (hooks/targets.yaml 에 없음)")
    if not t.get("run"):
        raise ExecError(f"대상 {name} 에 '실행' 명령이 없습니다")
    return t


def window_reason(window, now=None):
    """지금 실행해도 되면 None, 아니면 기다리는 이유."""
    w = str(window or "always").strip()
    if w in ("always", "언제나", "곧바로"):
        return None
    now = now or config.now()
    if len(w) == 5 and w[2] == "-" and w[:2].isdigit() and w[3:].isdigit():
        a, b = int(w[:2]), int(w[3:])
        ok = a <= now.hour < b if a < b else (now.hour >= a or now.hour < b)
        return None if ok else f"{a:02d}~{b:02d}시에만 실행"
    return f"모르는 창({w})이라 실행하지 않고 기다림"


def window_label(window):
    w = str(window or "always")
    if w in ("always", "언제나", "곧바로"):
        return "곧바로"
    if len(w) == 5 and w[2] == "-":
        return f"{w[:2]}~{w[3:]}시 사이"
    return f"창 {w}"


# ---------- 입력 파일 ----------

def _digest_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_input(paths, src):
    """입력 파일 사본을 장부에 떠 두고(읽기 전용) 이름·크기·해시를 돌려준다. 실행 때는 이 사본만 넘긴다."""
    src = Path(os.path.expanduser(str(src))).resolve()
    if not src.is_file():
        raise ExecError(f"입력 파일이 없습니다: {src}")
    size = src.stat().st_size
    if size > INPUT_MAX:
        raise ExecError(f"입력 파일이 너무 큽니다({size} 바이트, 한도 {INPUT_MAX})")
    digest = _digest_file(src)
    dest_dir = paths.attach / digest
    dest = dest_dir / src.name
    if not dest.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        os.chmod(dest, 0o400)
    return {"name": src.name, "size": size, "sha256": digest, "path": str(dest.relative_to(paths.ledger))}


def input_path(paths, meta):
    return paths.ledger / meta["path"]


def _input_now(paths, meta):
    p = input_path(paths, meta)
    return _digest_file(p) if p.is_file() else "없음"


# ---------- 저장소 대상 ----------

def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       **config.plat().popen_kw())
    if r.returncode != 0:
        raise ExecError(f"git {' '.join(args)}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def _repo(t):
    return os.path.expanduser(str(t["repo"]))


def path_objects(t, commit):
    return {p: git(_repo(t), "rev-parse", f"{commit}:{p}") for p in (t.get("paths") or ["."])}


def worktree_matches(t, commit):
    repo = _repo(t)
    branch = t.get("branch") or "main"
    if git(repo, "rev-parse", "--abbrev-ref", "HEAD") != branch:
        return f"저장소가 {branch} 가지가 아님"
    dirty = git(repo, "status", "--porcelain", "--", *(t.get("paths") or ["."]))
    if dirty:
        return "저장 안 된 변경이 있음: " + ", ".join(x.split(maxsplit=1)[-1] for x in dirty.splitlines()[:5])
    if path_objects(t, "HEAD") != path_objects(t, commit):
        return "봉인한 뒤 대상 경로의 내용이 바뀜"
    return None


# ---------- 봉인·서명 ----------

def seal_of(paths, payload):
    t = target_cfg(paths, payload["target"])
    body = {"kind": "run", "target": payload["target"], "recipe": t}
    if payload.get("input"):
        m = payload["input"]
        body["input"] = {"name": m["name"], "size": m["size"], "sha256": _input_now(paths, m)}
    if t.get("repo"):
        body["commit"] = payload["commit"]
        body["objects"] = path_objects(t, payload["commit"])
    return sha(canon(body))


def sign(key, request_id, seal):
    if not key:
        raise ExecError("서명 열쇠가 없습니다(금고의 seal-key)")
    return hmac.new(key.encode(), f"{request_id}|{seal}|승인".encode(), hashlib.sha256).hexdigest()


def sig_ok(key, r):
    if not key or not r["approval_sig"]:
        return False
    return hmac.compare_digest(r["approval_sig"], sign(key, r["id"], r["seal"]))


# ---------- 요청 만들기 (Jarvis 가 부름) ----------

def plain_from(summary, why, details):
    out = {}
    for (ko, en, _h, limit), v in zip(PLAIN_FIELDS, (summary, why, details)):
        v = " ".join(str(v or "").split()) if en == "summary" else str(v or "").strip()
        if len(v) > limit:
            raise ExecError(f"--{ko} 는 {limit}자까지입니다(지금 {len(v)}자)")
        out[en] = v
    if not out["summary"]:
        raise ExecError("--결론(무엇을 승인하는지 한 줄)이 있어야 합니다")
    return out


def new_request(paths, con, target, input_file=None, if_rejected="", plain_cols=None, actor="Jarvis", commit=None):
    """돌려주는 것: (요청 번호, 안내 글)."""
    if not str(if_rejected or "").strip():
        raise ExecError("거부하면 생기는 일(--if-rejected)이 있어야 합니다")
    t = target_cfg(paths, target)
    if t["input"] == "required" and not input_file:
        raise ExecError(f"대상 {target} 은 입력 파일(--input)이 있어야 합니다")
    if t["input"] == "none" and input_file:
        raise ExecError(f"대상 {target} 은 입력 파일을 받지 않습니다")
    payload = {"target": target}
    if input_file:
        payload["input"] = stage_input(paths, input_file)
    if t.get("repo"):
        payload["commit"] = commit or git(_repo(t), "rev-parse", "HEAD")
        why = worktree_matches(t, payload["commit"]) if not commit else None
        if why:
            raise ExecError(f"요청을 만들지 않았습니다: {why}")
    seal = seal_of(paths, payload)
    same = con.execute("select id from requests where seal=? and state in (?,?) order by id limit 1", (seal, *WAITING)).fetchone()
    if same:
        raise ExecError(f"같은 내용의 요청이 이미 기다리고 있습니다({rid(same['id'])}). 새로 내지 않았습니다.")
    cols = plain_cols or {}
    title = plain.cut(cols.get("summary") or t.get("name") or target, 120)
    with con:
        n = con.execute("insert into requests(target, payload, seal, created_at, created_by, updated_at, title, plain, if_rejected) "
                        "values (?,?,?,?,?,?,?,?,?)",
                        (target, canon(payload), seal, config.stamp(paths.cfg), actor, config.stamp(paths.cfg), title,
                         canon(cols), str(if_rejected).strip())).lastrowid
    worklog.add(f"{tag(n)} 승인 요청: {t.get('name') or target}", "대표 결정 기다림", f"jarvis exec show {rid(n)}",
                who=actor, paths=paths)
    return n, f"{rid(n)} 봉인 {seal[:8]}. 승인 대기로 올렸습니다({tag(n)}). 몇 초 안에 대표 DM 에 버튼과 함께 올라갑니다."


# ---------- 미리보기·승인 글 ----------

def get(con, n):
    return con.execute("select * from requests where id=?", (int(n),)).fetchone()


def plain_of(r):
    try:
        return json.loads(r["plain"] or "{}") or {}
    except (TypeError, ValueError):
        return {}


def preview(paths, r):
    """봉인된 내용에서 만든 기술 미리보기(작업용 칸)."""
    p = json.loads(r["payload"])
    lines = [f"실행 요청 {rid(r['id'])} · 봉인 {r['seal'][:12]} · 대상 {p['target']}"]
    try:
        t = target_cfg(paths, p["target"])
        lines.append(f"이름: {t.get('name') or p['target']} · 창: {window_label(t['window'])}")
        if t.get("repo"):
            lines.append(f"저장소: {t['repo']} ({t.get('branch') or 'main'}) · 커밋 {p.get('commit', '')[:10]}")
        lines += [f"$ {c}" for c in t["run"]]
        if t.get("check"):
            lines.append(f"확인: {t['check']}")
    except ExecError as e:
        lines.append(f"대상을 읽지 못함: {e}")
    m = p.get("input")
    if m:
        lines.append(f"입력 파일: {m['name']} ({m['size']} 바이트, sha256 {m['sha256'][:12]})")
        try:
            raw = input_path(paths, m).read_bytes()[:1500]
            lines.append("--- 입력 앞부분 ---\n" + raw.decode("utf-8", errors="replace"))
        except OSError:
            lines.append("(입력 사본을 읽지 못함)")
    return "\n".join(lines)


def sealed_fact(paths, r):
    """'승인하면 실제로 일어나는 일' 한 줄. 요청자의 설명이 아니라 봉인된 대상에서 만든다."""
    try:
        t = target_cfg(paths, json.loads(r["payload"])["target"])
        return f"승인하면: {window_label(t['window'])} '{t.get('name') or r['target']}' 을(를) 한 번 실행합니다."
    except Exception:  # noqa: BLE001
        return "승인하면: 맨 아래 작업용에 적힌 내용 그대로 한 번 실행합니다."


def approval_text(paths, r):
    """(글, 버튼 값). 버튼 값은 'R-n|봉인'."""
    cols = plain_of(r)
    parts = [f"✅ {tag(r['id'])} 승인 요청 · {r['created_by']}",
             f"**한 줄 결론** {plain.cut(cols.get('summary') or r['title'], 300)}",
             f"➜ {sealed_fact(paths, r)}"]
    if cols.get("why"):
        parts.append(f"**배경**\n{cols['why'][:800]}")
    if cols.get("details"):
        parts.append(f"**본문**\n{cols['details'][:1000]}")
    parts.append("거부하면: " + plain.cut(r["if_rejected"] or "실행하지 않습니다.", 300))
    text = "\n\n".join(parts) + plain.work("버튼은 아래 봉인된 내용대로 실행합니다\n" + preview(paths, r)[:1800])
    return text, f"{rid(r['id'])}|{r['seal']}"


def pending_approvals(con):
    return con.execute("select * from requests where state='봉인' order by id").fetchall()


# ---------- 결정 (jarvisd 가 부름) ----------

def parse_button(value):
    parts = str(value or "").split("|")
    if len(parts) == 2 and parts[0].upper().startswith("R-") and parts[0][2:].isdigit():
        return int(parts[0][2:]), parts[1]
    return None, None


def decide(paths, con, value, decision, key, note=""):
    """decision: 승인됨 | 거부됨 | 수정 요청. 문제가 있으면 대표가 읽는 이유, 없으면 None.
    두 번 결정되지 않는다: 요청이 '봉인'(승인 대기)일 때만 바꾼다."""
    n, shown = parse_button(value)
    if n is None:
        return "알 수 없는 버튼입니다."
    con.execute("begin immediate")
    try:
        r = get(con, n)
        if not r:
            con.execute("rollback")
            return "없는 요청입니다."
        if r["state"] != "봉인":
            con.execute("rollback")
            return f"반영하지 않았습니다. 이 건은 이미 '{r['state']}' 상태입니다."
        now = config.stamp(paths.cfg)
        if decision == "승인됨":
            if shown != r["seal"]:
                con.execute("update requests set state='실행 안 함', note=?, updated_at=? where id=?",
                            ("승인 화면의 봉인과 저장된 봉인이 다름", now, n))
                con.execute("commit")
                return "실행하지 않습니다. 이 글이 올라온 뒤 실행할 내용이 바뀌었습니다. 새로 신청해야 합니다."
            try:
                fresh = seal_of(paths, json.loads(r["payload"]))
            except Exception as e:  # noqa: BLE001
                fresh = f"계산 실패: {e}"
            if fresh != r["seal"]:
                con.execute("update requests set state='실행 안 함', note=?, updated_at=? where id=?",
                            ("승인 순간에 다시 계산한 봉인이 다름(대상 설정이나 입력이 바뀜)", now, n))
                con.execute("commit")
                return "실행하지 않습니다. 신청한 뒤 대상 설정이나 입력 파일이 바뀌었습니다. 새로 신청해야 합니다."
            con.execute("update requests set state='승인', approval_sig=?, approved_at=?, updated_at=? where id=?",
                        (sign(key, n, r["seal"]), now, now, n))
        elif decision == "거부됨":
            con.execute("update requests set state='거부', updated_at=? where id=?", (now, n))
        elif decision == "수정 요청":
            con.execute("update requests set state='수정 요청', decision_note=?, updated_at=? where id=?",
                        (str(note or "").strip()[:2000], now, n))
        else:
            con.execute("rollback")
            return f"모르는 결정: {decision}"
        con.execute("commit")
    except Exception:
        try:
            con.execute("rollback")
        except sqlite3.OperationalError:
            pass
        raise
    worklog.add(f"{tag(n)} {r['title']} 대표 결정 {decision}" + (f": {plain.cut(note, 200)}" if note else ""),
                decision, f"jarvis exec show {rid(n)}", who=paths.cfg.get("owner_title", "대표"), paths=paths)
    return None


# ---------- 실행 (실행기 데몬) ----------

def _tell(paths, text, dest="dm"):
    try:
        con = outbox.connect(paths)
        try:
            outbox.queue(con, dest, text)
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001  알림이 안 나가도 결과 기록은 그대로
        print(f"{config.stamp()} 알림 쌓기 실패: {e}", flush=True)


def _alerts_dest(paths):
    topics = (paths.cfg.get("telegram") or {}).get("topics") or {}
    return "긴급" if "긴급" in topics else "dm"


def _name(paths, r):
    try:
        return target_cfg(paths, r["target"]).get("name") or r["target"]
    except ExecError:
        return r["target"]


def finish(con, paths, r, state, result, line, detail=""):
    con.execute("update requests set state=?, result=?, updated_at=? where id=?",
                (state, str(result)[-4000:], config.stamp(paths.cfg), r["id"]))
    con.commit()
    worklog.add(f"{tag(r['id'])} {_name(paths, r)} 실행", f"{state}: {plain.cut(line, 150)}", f"jarvis exec show {rid(r['id'])}",
                who="실행기", paths=paths)
    icon = {"완료": "✅", "실패": "⚠️", "불확실": "⚠️", "실행 안 함": "⚠️"}.get(state, "ℹ️")
    dest = "dm" if state == "완료" else _alerts_dest(paths)
    _tell(paths, f"{icon} {tag(r['id'])} {_name(paths, r)}: {line}" + plain.work(detail or f"{rid(r['id'])} · {state}"), dest)


def refuse(con, paths, r, why):
    finish(con, paths, r, "실행 안 함", why,
           f"승인하신 일을 하지 않았습니다. 이유: {why}. 자동으로 다시 하지 않습니다. 계속하려면 Jarvis 가 고쳐 새로 승인을 요청합니다.",
           f"{rid(r['id'])} 실행 안 함: {why}")


def _env(paths, r, p):
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_SEAL")}
    env["JARVIS_REQUEST_ID"] = rid(r["id"])
    env["JARVIS_HOME"] = str(paths.home)
    env["JARVIS_PYTHON"] = config.plat().console_python(sys.executable)
    env["PYTHONPATH"] = str(config.ENGINE_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("PYTHONUTF8", "1")
    if p.get("input"):
        env["JARVIS_PAYLOAD"] = str(input_path(paths, p["input"]))
    return env


def shell(cmd, cwd, env, timeout):
    """대상 명령 한 줄을 bash 로(맥 /bin/bash, 윈도 Git Bash). 대상 문법이 OS 와 상관없이 같다."""
    plat = config.plat()
    r = subprocess.run([plat.bash(), "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, **plat.popen_kw())
    return r.returncode, (r.stdout + r.stderr)[-1500:]


def process(con, paths, r, key, now=None):
    p = json.loads(r["payload"])
    if not sig_ok(key, r):
        return refuse(con, paths, r, "승인 서명이 맞지 않음(요청이 바뀌었을 수 있음)")
    try:
        t = target_cfg(paths, p["target"])
    except ExecError as e:
        return refuse(con, paths, r, str(e))
    why = window_reason(t["window"], now)
    if why:
        note = f"기다림: {why}"
        if r["note"] != note:
            con.execute("update requests set note=?, updated_at=? where id=?", (note, config.stamp(paths.cfg), r["id"]))
            con.commit()
        return None
    try:
        if seal_of(paths, p) != r["seal"]:
            return refuse(con, paths, r, "봉인이 맞지 않음(대상 설정이나 입력 파일이 승인 뒤에 바뀜)")
        if t.get("repo"):
            changed = worktree_matches(t, p["commit"])
            if changed:
                return refuse(con, paths, r, changed)
    except ExecError as e:
        return refuse(con, paths, r, f"내용 확인 실패: {e}")
    paths.attempts.mkdir(parents=True, exist_ok=True)
    marker = paths.attempts / f"{rid(r['id'])}.json"
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return finish(con, paths, r, "불확실", "",
                      "전에 실행하려던 흔적이 있어 다시 하지 않았습니다. 결과를 직접 확인해 주세요.",
                      f"{rid(r['id'])} 시도 표시 파일이 이미 있음: {marker}")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"at": config.stamp(paths.cfg), "seal": r["seal"]}, f)
        f.flush()
        os.fsync(f.fileno())
    con.execute("update requests set state='실행 중', updated_at=? where id=?", (config.stamp(paths.cfg), r["id"]))
    con.commit()  # 실행 전에 남긴다. 실행기가 죽어도 다시 하지 않는다
    cwd = _repo(t) if t.get("repo") else str(paths.home)
    env = _env(paths, r, p)
    timeout = int(float(t.get("timeout_min") or 30) * 60)
    log, code, step = [], 0, ""
    try:
        for cmd in t["run"]:
            code, out = shell(cmd, cwd, env, timeout)
            log.append(f"$ {cmd} → {code}\n{out}")
            if code != 0:
                step = cmd
                break
        if code == 0 and t.get("check"):
            code, out = shell(str(t["check"]), cwd, env, 300)
            log.append(f"확인 → {code}\n{out}")
            step = "확인" if code else ""
    except subprocess.TimeoutExpired:
        return finish(con, paths, r, "불확실", "\n".join(log),
                      f"{timeout // 60}분 안에 끝나지 않아 멈췄습니다. 어디까지 됐는지 확실하지 않아 다시 하지 않습니다.",
                      f"{rid(r['id'])} 시간 초과")
    if code == 0:
        return finish(con, paths, r, "완료", "\n".join(log), "끝났습니다(대표님 승인대로).",
                      f"{rid(r['id'])} 완료\n" + "\n".join(log)[-800:])
    return finish(con, paths, r, "실패", "\n".join(log),
                  "실패했습니다. 자동으로 다시 하지 않습니다. 계속하려면 Jarvis 가 원인을 고쳐 새로 승인을 요청합니다.",
                  f"{rid(r['id'])} 멈춘 단계: {step}\n" + "\n".join(log)[-800:])


def tick(paths, key, now=None):
    if paths.pause.exists():
        return 0
    con = connect(paths)
    n = 0
    try:
        for r in con.execute("select * from requests where state='승인' order by id").fetchall():
            try:
                process(con, paths, r, key, now)
                n += 1
            except Exception as e:  # noqa: BLE001
                con.rollback()
                print(f"{config.stamp()} {rid(r['id'])} 처리 오류: {e}", flush=True)
    finally:
        con.close()
    return n


def recover_crashed(paths):
    """시작할 때: '실행 중'에 멈춘 요청은 다시 하지 않는다(불확실 + 알림)."""
    con = connect(paths)
    try:
        for r in con.execute("select * from requests where state='실행 중'").fetchall():
            finish(con, paths, r, "불확실", "", "실행 도중 실행기가 멈춰 결과가 확실하지 않습니다. 다시 하지 않습니다.",
                   f"{rid(r['id'])} 실행 중에 실행기가 멈춤")
    finally:
        con.close()


def daemon(paths):
    key = secrets.get(secrets.SEAL, paths.cfg)
    if not key:
        print("서명 열쇠(seal-key)가 금고(키체인·자격 증명 관리자)에 없습니다. /jarvis:setup 을 다시 돌리세요.", file=sys.stderr)
        return 2
    recover_crashed(paths)
    print(f"{config.stamp()} 실행기 시작", flush=True)
    every = int(paths.cfg.get("executor_tick_sec") or 30)
    while True:
        tick(paths, key)
        time.sleep(every)


def pending_text(con):
    out = []
    for label, state in (("대표 결정을 기다림", "봉인"), ("승인됐고 실행 기다림", "승인"), ("실행 중", "실행 중")):
        for r in con.execute("select * from requests where state=? order by id", (state,)).fetchall():
            note = f" · {plain.cut(r['note'], 120)}" if r["note"] else ""
            out.append(f"{label}: {rid(r['id'])} {tag(r['id'])} · {r['target']} · {plain.cut(r['title'], 80)}{note}")
    return "\n".join(out) or "기다리는 요청 없음"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jarvis exec", description="실행 요청. 실행은 대표 승인 뒤 실행기가 한 번만 한다.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("request", help="실행 요청(=승인 요청) 만들기")
    q.add_argument("--target", required=True, help="hooks/targets.yaml 의 대상 이름")
    q.add_argument("--input", help="대상에 넘길 입력 파일(사본을 봉인)")
    q.add_argument("--commit", help="저장소 대상: 봉인할 커밋(기본 지금 HEAD)")
    q.add_argument("--if-rejected", required=True, help="거부하면 생기는 일")
    for ko, en, h, limit in PLAIN_FIELDS:
        q.add_argument(f"--{ko}", f"--{en}", dest=en, default="", help=f"{h} ({limit}자까지)")
    sub.add_parser("list", help="최근 요청 30건")
    sub.add_parser("pending", help="기다리는 요청")
    s = sub.add_parser("show", help="요청 한 건(R-0001 · 1 · #요청1)")
    s.add_argument("id")
    sub.add_parser("targets", help="실행 대상 목록")
    sub.add_parser("pause", help="실행기 멈추기(다시 켜기는 대표가 터미널에서 resume)")
    sub.add_parser("resume", help="실행기 다시 켜기(대표 몫)")
    sub.add_parser("daemon", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    paths = config.Paths()
    try:
        if a.cmd == "daemon":
            return daemon(paths)
        if a.cmd == "targets":
            ts = load_targets(paths)
            for k, t in ts.items():
                print(f"{k}  {t.get('name') or ''}  ({window_label(t['window'])}, 입력 {t['input']})")
            if not ts:
                print("대상이 없습니다. hooks/targets.yaml 을 보세요.")
            return 0
        if a.cmd == "pause":
            paths.pause.parent.mkdir(parents=True, exist_ok=True)
            paths.pause.write_text(config.stamp(paths.cfg), encoding="utf-8")
            print("멈췄습니다. 다시 켜기는 대표가 터미널에서: jarvis exec resume")
            return 0
        if a.cmd == "resume":
            if paths.pause.exists():
                paths.pause.unlink()
            print("다시 켰습니다.")
            return 0
        con = connect(paths)
        if a.cmd == "list":
            for r in con.execute("select * from requests order by id desc limit 30"):
                print(f"{rid(r['id'])}  {r['target']}  {r['state']}  {plain.cut(r['title'], 60)}  {r['note'] or ''}")
            return 0
        if a.cmd == "pending":
            print(pending_text(con))
            return 0
        if a.cmd == "show":
            r = get(con, parse_rid(a.id))
            if not r:
                raise ExecError("없는 요청")
            said = f"\n대표 수정 요청: {r['decision_note']}" if r["decision_note"] else ""
            print(f"{rid(r['id'])} ({tag(r['id'])}) {r['state']} · 봉인 {r['seal'][:12]}\n무엇: {r['title']}\n"
                  f"{preview(paths, r)}{said}\n메모: {r['note'] or '-'}\n결과: {(r['result'] or '-')[:1500]}")
            return 0
        cols = plain_from(a.summary, a.why, a.details)
        actor = os.environ.get("JARVIS_HQ_AGENT") or "터미널"
        _, msg = new_request(paths, con, a.target, a.input, a.if_rejected, cols, actor=actor, commit=a.commit)
        print(msg)
        return 0
    except ExecError as e:
        print(str(e), file=sys.stderr)
        return 1
