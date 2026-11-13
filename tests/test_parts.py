"""작은 부품: 텔레그램 모양·받기 거르기, 지킴이, 권한 빌드, 한 일 기록, 예약 cron, 요약 재료, 설정 바꾸기, 받아쓰기·Gmail 모듈."""

import io
import json
import subprocess
import time
import urllib.error
from datetime import datetime

import pytest

from conftest import PLUGIN
from jhq import apply_config, brief, config, cronlib, executor, perms, telegram, watchdog, worklog
from jhq.extras import gmail, stt


# ---------- 텔레그램 ----------

def test_to_html_and_work_fold():
    h = telegram.to_html("**결과** 됐습니다 <b>\n`jarvis log`\n```\na < b\n```\n⟦작업용⟧\nR-0001 경로")
    assert "<b>결과</b>" in h and "&lt;b&gt;" in h and "<code>jarvis log</code>" in h
    assert "<pre>a &lt; b</pre>" in h and "<blockquote expandable>작업용\nR-0001 경로</blockquote>" in h


def test_split_long():
    parts = telegram.split("줄\n" * 3000, size=1000)
    assert len(parts) > 1 and all(len(p) <= 1000 for p in parts)


def make_msgr(group=None):
    cfg = {"telegram": {"owner_id": 42, "group_id": group, "topics": {"승인": 7} if group else {}}}
    return telegram.Messenger(telegram.Bot("123:abc"), cfg)


def test_parse_only_owner():
    m = make_msgr()
    own = {"update_id": 1, "message": {"message_id": 5, "chat": {"id": 42}, "from": {"id": 42}, "text": "안녕"}}
    other = {"update_id": 2, "message": {"message_id": 6, "chat": {"id": 99}, "from": {"id": 99}, "text": "hi"}}
    stranger_in_dm = {"update_id": 3, "message": {"message_id": 7, "chat": {"id": 42}, "from": {"id": 99}, "text": "hi"}}
    assert m.parse(own)[0]["text"] == "안녕" and m.parse(own)[0]["dm"]
    assert m.parse(other) == [] and m.parse(stranger_in_dm) == []


def test_parse_buttons_and_leave():
    m = make_msgr()
    q = {"update_id": 1, "callback_query": {"id": "c1", "from": {"id": 42}, "data": "b:2",
                                            "message": {"message_id": 9, "chat": {"id": 42}}}}
    assert m.parse(q)[0] == {"kind": "button", "id": "c1", "chat": 42, "msg": 9, "index": 2}
    q["callback_query"]["from"]["id"] = 99
    assert m.parse(q)[0]["kind"] == "answer"
    leave = {"update_id": 2, "my_chat_member": {"chat": {"id": -5, "title": "x"}, "from": {"id": 99},
                                                "new_chat_member": {"status": "member"}}}
    assert m.parse(leave)[0]["kind"] == "leave"


def test_topic_routing():
    m = make_msgr(group=-77)
    assert m.where("승인") == (-77, 7)
    assert m.where("없는토픽") == (42, None)
    assert m.where("dm") == (42, None)


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_bot_retries_429_and_masks_token():
    seq = [{"ok": False, "error_code": 429, "parameters": {"retry_after": 0}}, {"ok": True, "result": {"x": 1}}]
    slept = []

    def opener(req, timeout=0):
        return Resp(json.dumps(seq.pop(0)).encode())
    b = telegram.Bot("777:SECRET", opener=opener, sleep=slept.append)
    assert b.call("getMe") == {"x": 1} and slept

    def bad(req, timeout=0):
        raise urllib.error.URLError("https://api.telegram.org/bot777:SECRET/getMe 실패")
    b = telegram.Bot("777:SECRET", opener=bad)
    with pytest.raises(ConnectionError) as e:
        b.call("getMe")
    assert "SECRET" not in str(e.value)


# ---------- 지킴이 ----------

def fake_run(listing, calls):
    def run(argv, **kw):
        calls.append(argv)
        out = listing if argv[:2] == ["launchctl", "list"] else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
    return run


def test_watchdog_restarts_stale_after_confirm(env):
    cfg, paths = env
    listing = "PID\tStatus\tLabel\n111\t0\tcom.jarvis-hq.jarvisd\n222\t0\tcom.jarvis-hq.executor\n"
    paths.heartbeat.write_text(json.dumps({"flush": time.time() - 900, "poll": time.time() - 900}))
    calls, sent = [], []
    now = time.time()
    p1 = watchdog.run_once(cfg, paths, run=fake_run(listing, calls), send=lambda t: sent.append(t) or True, now=now)
    assert p1 == {} and not any(c[:2] == ["launchctl", "kickstart"] for c in calls)  # 처음 본 것은 의심만
    p2 = watchdog.run_once(cfg, paths, run=fake_run(listing, calls), send=lambda t: sent.append(t) or True, now=now + 300)
    assert "com.jarvis-hq.jarvisd" in p2
    assert any(c[:2] == ["launchctl", "kickstart"] for c in calls) and sent


def test_watchdog_missing_service(env):
    cfg, paths = env
    calls, sent = [], []
    p = watchdog.run_once(cfg, paths, run=fake_run("PID\tStatus\tLabel\n", calls), send=lambda t: sent.append(t) or True)
    assert "등록" in p["com.jarvis-hq.jarvisd"] and sent
    assert not any(c[:2] == ["launchctl", "kickstart"] for c in calls)


# ---------- 권한 ----------

def test_perms_build_and_locks(env):
    _cfg, paths = env
    code, msg = perms.build(paths)
    assert code == 0
    doc = json.loads(paths.settings.read_text())
    assert "Read(**/.env)" in doc["permissions"]["deny"] and "Bash" in doc["permissions"]["allow"]
    assert "gate.py" in json.dumps(doc["hooks"])
    assert perms.check(paths)[0] == 0
    user = json.loads(paths.permissions.read_text())
    user["unlock"] = ["Read(**/.env)"]
    paths.permissions.write_text(json.dumps(user))
    assert perms.build(paths)[0] == 2
    assert perms.build(paths, owner_approval="대표가 허락")[0] == 0
    assert "Read(**/.env)" not in json.loads(paths.settings.read_text())["permissions"]["deny"]


def test_perms_refuses_hand_edit(env):
    _cfg, paths = env
    perms.build(paths)
    doc = json.loads(paths.settings.read_text())
    doc["permissions"]["allow"].append("mcp__x")
    paths.settings.write_text(json.dumps(doc))
    assert perms.build(paths)[0] == 3
    assert perms.build(paths, force=True)[0] == 0
    assert paths.settings.with_name("settings.json.bak").exists()


# ---------- 기록·cron·요약 ----------

def test_worklog_add_and_since(env):
    cfg, paths = env
    at = config.now(cfg).replace(hour=10, minute=0)
    assert worklog.add("시험 · 한 일", "완료", "근거", at=at, paths=paths)
    got = worklog.since(at.replace(hour=9), paths)
    assert len(got) == 1 and "시험 / 한 일" in got[0]


def test_cron():
    t = datetime(2026, 1, 5, 9, 30)  # 월요일
    assert cronlib.cron_match("30 9 * * 1", t) and cronlib.cron_match("*/15 9 * * 1-5", t)
    assert not cronlib.cron_match("30 9 * * 0", t)
    assert cronlib.valid("0 9 * * *") and not cronlib.valid("매일")


def test_brief_collect(env):
    cfg, paths = env
    now = config.now(cfg)
    worklog.add("아침에 한 일", "완료", paths=paths, at=now)
    (paths.harness / "todo.md").write_text("# 할 일\n- [ ] 견적서 보내기\n- [x] 지난주 보고\n", encoding="utf-8")
    out = brief.collect("evening", paths, since=now.replace(hour=0, minute=0), now=now, with_services=False)
    assert "아침에 한 일" in out and "견적서 보내기" in out and "지난주 보고" not in out and "[오늘 memory" in out


# ---------- 설정 바꾸기(config-apply) ----------

def test_apply_config_backs_up_and_validates(env, tmp_path):
    _cfg, paths = env
    old = paths.targets.read_text(encoding="utf-8")
    new = old.replace("실행기 시험(아무것도 바꾸지 않음)", "실행기 시험 2")
    payload = tmp_path / "p.json"
    payload.write_text(json.dumps({"file": "targets.yaml", "content": new}, ensure_ascii=False), encoding="utf-8")
    apply_config.apply(payload, paths)
    assert "실행기 시험 2" in paths.targets.read_text(encoding="utf-8")
    backups = list((paths.state / "backup").rglob("targets.yaml"))
    assert backups and backups[0].read_text(encoding="utf-8") == old
    payload.write_text(json.dumps({"file": "../../etc/passwd", "content": "x"}))
    with pytest.raises(SystemExit):
        apply_config.apply(payload, paths)


# ---------- 선택 모듈 ----------

def test_stt_reports_missing_tools(env, monkeypatch, capsys):
    cfg, _paths = env
    cfg = dict(cfg, extras={"stt": {"ffmpeg": "/없음/ffmpeg", "whisper": "/없음/whisper-cli", "model": "/없음/m.bin"}})
    monkeypatch.setattr(stt.config, "load", lambda: cfg)
    assert stt.main(["doctor"]) == 3
    assert "brew install" in capsys.readouterr().out


def test_gmail_payload_rules():
    with pytest.raises(executor.ExecError, match="Re:"):
        gmail.build_payload("a@example.com", "Re: 견적", "본문")
    p = gmail.build_payload("a@example.com", "Re: 견적", "본문", reply_to="<x@example.com>", thread_id="t1")
    assert p["in_reply_to"] == "<x@example.com>"
    with pytest.raises(executor.ExecError):
        gmail.build_payload("주소아님", "제목", "본문")


def test_gmail_send_uses_sealed_payload(env, tmp_path):
    cfg, _paths = env
    from jhq import secrets
    for n in (gmail.CLIENT_ID, gmail.CLIENT_SECRET, gmail.REFRESH):
        secrets.put(n, "v-" + n, cfg)
    f = tmp_path / "mail.json"
    f.write_text(json.dumps(gmail.build_payload("a@example.com", "안녕", "본문 글")), encoding="utf-8")
    seen = []

    def opener(req, timeout=0):
        seen.append(req.full_url)
        if "token" in req.full_url:
            return Resp(json.dumps({"access_token": "tok"}).encode())
        body = json.loads(req.data)
        import base64
        raw = base64.urlsafe_b64decode(body["raw"]).decode()
        assert "To: a@example.com" in raw and "Subject:" in raw
        return Resp(json.dumps({"id": "m1"}).encode())
    assert gmail.send(f, cfg, opener=opener) == "m1"
    assert len(seen) == 2


def test_gmail_request_goes_through_executor(env, tmp_path, monkeypatch):
    _cfg, paths = env
    import yaml
    doc = yaml.safe_load(paths.targets.read_text(encoding="utf-8"))
    doc["대상"]["gmail-send"] = {"이름": "Gmail", "입력": "필수", "실행": ['"$JARVIS_PYTHON" -m jhq.extras.gmail send']}
    paths.targets.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    body = tmp_path / "b.txt"
    body.write_text("본문")
    assert gmail.main(["request", "--to", "a@example.com", "--subject", "안녕", "--body-file", str(body),
                       "--if-rejected", "안 보냄"]) == 0
    con = executor.connect(paths)
    r = con.execute("select * from requests").fetchone()
    assert r["target"] == "gmail-send" and r["state"] == "봉인"
    assert "a@example.com" in executor.preview(paths, r)


def test_gmail_send_entry_refuses_without_request(monkeypatch, capsys):
    monkeypatch.delenv("JARVIS_REQUEST_ID", raising=False)
    assert gmail.main(["send"]) == 2


# ---------- 문서 ----------

def test_rules_are_short_and_skills_parse():
    import yaml
    for f in (PLUGIN / "template" / "rules").glob("*.md"):
        assert len(f.read_text(encoding="utf-8")) < 10000, f
    names = set()
    for f in (PLUGIN / "skills").glob("*/SKILL.md"):
        head = f.read_text(encoding="utf-8").split("---")[1]
        meta = yaml.safe_load(head)
        assert meta["name"] == f.parent.name and len(meta["description"]) > 20
        names.add(meta["name"])
    assert {"setup", "uninstall", "doctor", "approval-request", "code-work"} <= names


# 주인이 일부러 넣은 바깥 스킬. 원본 그대로 두므로(이름·내용 안 바꿈) 이 저장소의 글 규칙(엠대시 금지)을 걸지 않는다.
# 세무 검토 스킬 이름에는 개인정보 검사가 그 폴더 밖에서 막는 낱말이 들어 있어 이름 대신 해시로 적는다(scripts/check_clean.py).
VENDORED_SKILLS = ("proposal-deck-kr",)
# 한국어 글쓰기 규칙(Threads 수집을 정리한 것). 13-문장부호 는 엠대시 자체를 다루고, 출처 목록은 남의 글을 옮겨 적는다
VENDORED_RULES = ("11-한국어-문장.md", "12-한국어-낱말.md", "13-문장부호.md", "threads-ai-style-sources.md")
VENDORED_SKILL_HASHES = ("6d973c8bd44806809548be79",)


def vendored(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_clean_v", PLUGIN.parent.parent / "scripts" / "check_clean.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return name in VENDORED_SKILLS or mod.term_hash(name) in VENDORED_SKILL_HASHES


def test_vendored_skills_are_present_and_unchanged_in_name():
    names = [d.name for d in (PLUGIN / "skills").iterdir() if d.is_dir() and vendored(d.name)]
    assert len(names) == 2
    import yaml
    for n in names:
        meta = yaml.safe_load((PLUGIN / "skills" / n / "SKILL.md").read_text(encoding="utf-8").split("---")[1])
        assert meta["name"] == n
    mcp = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["korea-tax-law"]["type"] == "http"


def test_no_em_dash_in_docs():
    root = PLUGIN.parent.parent
    for f in list((PLUGIN / "template").rglob("*.md")) + list((PLUGIN / "skills").rglob("*.md")) + \
            list((root / "docs").glob("*.md")) + [root / "README.md"]:
        rel = f.relative_to(root).parts
        if (rel[2:3] == ("skills",) and vendored(rel[3])) or (rel[2:3] == ("template",) and f.name in VENDORED_RULES):
            continue
        if f.exists():
            assert "—" not in f.read_text(encoding="utf-8"), f



def test_korean_writing_rules_cross_refs():
    """들여온 글쓰기 규칙끼리 새 이름으로 가리키고, 출처 주석(맨 위 HTML 주석)이 남아 있다."""
    rules = PLUGIN / "template" / "rules"
    for name in VENDORED_RULES[:3]:
        text = (rules / name).read_text(encoding="utf-8")
        assert text.startswith("<!--") and "출처" in text.split("-->")[0]
        assert "03-korean" not in text and "04-punctuation" not in text
        assert "threads-ai-style-sources.md" not in text.replace("docs/threads-ai-style-sources.md", "")
    index = (PLUGIN / "template" / "RULES.md").read_text(encoding="utf-8")
    assert all(f"rules/{n}" in index for n in VENDORED_RULES[:3])
    assert "11-" not in (PLUGIN / "template" / "CLAUDE.md").read_text(encoding="utf-8")  # 늘 불러오는 목록에는 넣지 않음
