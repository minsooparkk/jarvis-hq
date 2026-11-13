"""jarvisd: 가짜 텔레그램·가짜 claude 로 대화·진행 표시·합치기·승인 버튼·예약."""

import json
import sys
import textwrap
import threading
import time
from datetime import datetime

import pytest

from conftest import seal_key
from jhq import config, daemon, executor, outbox, telegram


class FakeBot:
    def __init__(self):
        self.calls = []

    def call(self, method, **params):
        self.calls.append((method, params))
        return {}

    def download(self, file_id, dest_dir, name=None):
        p = dest_dir / (name or "f.bin")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("내용")
        return p


class FakeMessenger:
    def __init__(self, topics=None):
        self.owner, self.group, self.topics = 42, None, topics or {}
        self.sent, self.edits, self.answers, self.n, self.bot = [], [], [], 100, FakeBot()
        self.lock = threading.Lock()

    def send(self, dest, text, buttons=None, reply_to=None, force_reply=False):
        with self.lock:
            self.n += 1
            self.sent.append({"dest": dest, "text": text, "buttons": buttons, "msg": self.n, "force": force_reply})
            return 42, self.n

    def send_file(self, dest, path, caption=""):
        return self.send(dest, f"[파일 {path}] {caption}")

    def edit(self, chat, msg, text, buttons=None):
        self.edits.append({"chat": chat, "msg": msg, "text": text})

    def answer(self, cid, text):
        self.answers.append(text)

    def typing(self, dest):
        pass

    def react(self, chat, msg, on=True):
        pass

    def texts(self):
        return [s["text"] for s in self.sent]

    def download(self, f, dest_dir):
        return self.bot.download(f["id"], dest_dir, f.get("name"))

    def leave(self, chat):
        self.bot.call("leaveChat", chat_id=chat)


def dm(text, msg=1, reply_to=None):
    return {"kind": "message", "chat": 42, "msg": msg, "topic": None, "topic_name": None, "dm": True, "text": text,
            "reply_to": reply_to}


@pytest.fixture
def d(env):
    cfg, paths = env
    calls = []

    def runner(cfg, paths, prompt, session, resume=False, context="", timeout=None, on_text=None, on_tool=None,
               on_tick=None, register=None):
        calls.append({"prompt": prompt, "session": session, "resume": resume, "context": context})
        if on_text:
            on_text("메일함부터 볼게요.")
        if on_tool:
            on_tool("Read")
        return f"답: {prompt.splitlines()[-1]}"

    dm_ = daemon.Daemon(cfg, paths, FakeMessenger(), seal_key(cfg), runner=runner)
    dm_.calls = calls
    return dm_


def test_dm_answer_and_same_day_session(d):
    d.handle_message(dm("안녕"))
    assert d.msgr.texts() == ["메일함부터 볼게요.", "답: 안녕"]
    assert d.calls[0]["resume"] is False and "텔레그램 DM" in d.calls[0]["context"]
    d.handle_message(dm("또", msg=2))
    assert d.calls[1]["resume"] is True and d.calls[1]["session"] == d.calls[0]["session"]
    assert json.loads(d.paths.daemon_state.read_text())["last_reply_at"]


def test_new_command_resets_session(d):
    d.handle_message(dm("안녕"))
    d.handle_message(dm("/new", msg=2))
    d.handle_message(dm("다시", msg=3))
    assert d.calls[-1]["resume"] is False
    assert any("새로 시작" in t for t in d.msgr.texts())


def test_status_and_help_commands_skip_claude(d):
    d.handle_message(dm("/상태"))
    d.handle_message(dm("도움", msg=2))
    assert not d.calls
    assert "상태" in d.msgr.texts()[0] and "/new" in d.msgr.texts()[1]


def test_messages_during_answer_are_merged(env):
    cfg, paths = env
    gate, calls = threading.Event(), []

    def slow(cfg, paths, prompt, session, resume=False, context="", **kw):
        calls.append(prompt)
        if len(calls) == 1:
            gate.wait(5)
        return f"답{len(calls)}"

    dd = daemon.Daemon(cfg, paths, FakeMessenger(), seal_key(cfg), runner=slow)
    t = threading.Thread(target=dd.handle_message, args=(dm("첫 말"),))
    t.start()
    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    dd.handle_message(dm("덧붙임 말", msg=2))
    gate.set()
    t.join(5)
    assert "말씀 받았습니다" in dd.msgr.texts()[0]
    assert len(calls) == 2 and "덧붙임 말" in calls[1] and "답1" in calls[1]
    assert dd.msgr.texts()[-1] == "답2"
    assert dd.msgr.texts().count("답1") == 0


def test_file_is_received_into_inbox(d):
    ev = dm("이거 봐")
    ev["file"] = {"kind": "document", "id": "f1", "name": "a.pdf", "size": 10}
    d.handle_message(ev)
    assert "[파일 첨부:" in d.calls[0]["prompt"] and str(d.paths.inbox) in d.calls[0]["prompt"]


def test_approval_post_button_and_execution(d):
    paths = d.paths
    con = executor.connect(paths)
    n, _ = executor.new_request(paths, con, "hello", None, "안 함", {"summary": "시험", "why": "", "details": ""})
    con.close()
    d.flush_once()
    posts = [s for s in d.msgr.sent if s["buttons"]]
    assert len(posts) == 1 and "승인 요청" in posts[0]["text"]
    d.flush_once()
    assert len([s for s in d.msgr.sent if s["buttons"]]) == 1  # 한 번만 올린다
    d.handle_button({"kind": "button", "id": "q", "chat": 42, "msg": posts[0]["msg"], "index": 0})
    con = executor.connect(paths)
    assert executor.get(con, n)["state"] == "승인"
    con.close()
    assert d.msgr.edits and "승인했습니다" in d.msgr.edits[0]["text"]
    d.handle_button({"kind": "button", "id": "q2", "chat": 42, "msg": posts[0]["msg"], "index": 2})
    assert "지난 버튼" in d.msgr.answers[-1]  # 결정 뒤에는 버튼이 거둬져 다시 먹지 않는다
    executor.tick(paths, d.key)
    d.flush_once()
    assert any("끝났습니다" in t for t in d.msgr.texts())


def test_revise_flow(d):
    paths = d.paths
    con = executor.connect(paths)
    n, _ = executor.new_request(paths, con, "hello", None, "안 함", {"summary": "시험", "why": "", "details": ""})
    con.close()
    d.flush_once()
    post = [s for s in d.msgr.sent if s["buttons"]][0]
    d.handle_button({"kind": "button", "id": "q", "chat": 42, "msg": post["msg"], "index": 1})
    ask = d.msgr.sent[-1]
    assert ask["force"] and "무엇을 고칠까요" in ask["text"]
    d.handle_message(dm("제목을 바꿔 주세요", msg=9, reply_to=ask["msg"]))
    con = executor.connect(paths)
    r = executor.get(con, n)
    con.close()
    assert r["state"] == "수정 요청" and r["decision_note"] == "제목을 바꿔 주세요"
    assert not d.calls  # 수정 메모는 claude 를 깨우지 않는다


def test_outbox_flush_and_failure(d):
    con = outbox.connect(d.paths)
    outbox.queue(con, "dm", "알림 하나")
    d.flush_once()
    assert "알림 하나" in d.msgr.texts()
    assert not outbox.due(con)

    def boom(*a, **k):
        raise telegram.TgError("sendMessage", 400, "chat not found")
    d.msgr.send = boom
    outbox.queue(con, "dm", "실패할 글")
    d.flush_once()
    row = con.execute("select * from outbox order by id desc limit 1").fetchone()
    assert row["posted_at"] == "실패"


def test_scheduler_runs_script_job(d):
    (d.paths.home / "schedule.yaml").write_text(textwrap.dedent("""
        작업:
          - 이름: 인사
            언제: "*/5 * * * *"
            종류: 스크립트
            실행: echo 예약 인사
            보낼곳: DM
            상태: 켬
          - 이름: 꺼진것
            언제: "* * * * *"
            종류: 스크립트
            실행: echo 안 돌아야 함
            상태: 끔
    """), encoding="utf-8")
    t = datetime(2026, 1, 5, 9, 10, tzinfo=config.tz())
    due = d.scheduler_tick(now=t)
    assert [j["name"] for _o, _f, j, _m in due] == ["인사"]
    assert d.scheduler_tick(now=t) == []  # 같은 분은 한 번만
    owner, folder, j, m = due[0]
    d.run_job(owner, folder, j, m)
    assert any("예약 인사" in x for x in d.msgr.texts())


def test_scheduler_prompt_job_and_quiet(d):
    def quiet_runner(cfg, paths, prompt, session, resume=False, context="", **kw):
        return "⟦알릴 것 없음⟧"
    d.runner = quiet_runner
    job = daemon.norm_job({"이름": "조용", "언제": "0 9 * * *", "종류": "지시", "실행": "스킬을 읽고 그대로", "보낼곳": "DM"})
    d.run_job("Jarvis", d.paths.home, job, datetime(2026, 1, 5, 9, 0))
    assert d.msgr.sent == []


def test_failed_job_alerts_once(d):
    job = daemon.norm_job({"이름": "고장", "언제": "* * * * *", "종류": "스크립트", "실행": "exit 3"})
    d.run_job("Jarvis", d.paths.home, job, datetime(2026, 1, 5, 9, 0))
    d.run_job("Jarvis", d.paths.home, job, datetime(2026, 1, 5, 9, 1))
    alerts = [t for t in d.msgr.texts() if "실패" in t]
    assert len(alerts) == 1 and d.job_fail["Jarvis/고장"]["n"] == 2


def test_heartbeat(d):
    d.flush_once()
    hb = json.loads(d.paths.heartbeat.read_text())
    assert time.time() - hb["flush"] < 5


def test_norm_job_english_keys():
    j = daemon.norm_job({"name": "a", "cron": "0 9 * * *", "kind": "script", "run": "true", "to": "#긴급", "enabled": "on"})
    assert j["kind"] == "script" and j["to"] == "긴급" and j["enabled"]


def fake_claude(tmp_path, body):
    p = tmp_path / "fake-claude"
    p.write_text(f"#!{sys.executable}\nimport json, sys, time\n" + textwrap.dedent(body))
    p.chmod(0o755)
    return str(p)


def test_run_claude_parses_stream(env, tmp_path):
    cfg, paths = env
    cfg = dict(cfg, claude=fake_claude(tmp_path, """
        assert "--output-format" in sys.argv and "stream-json" in sys.argv
        pr = lambda o: print(json.dumps(o, ensure_ascii=False), flush=True)
        pr({"type": "system", "subtype": "init"})
        pr({"type": "assistant", "message": {"content": [{"type": "text", "text": "확인부터 할게요."},
                                                         {"type": "tool_use", "name": "Bash", "input": {}}]}})
        pr({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}})
        pr({"type": "assistant", "message": {"content": [{"type": "text", "text": "다 됐습니다."}]}})
        pr({"type": "result", "subtype": "success", "is_error": False, "result": "다 됐습니다."})
    """))
    said, tools = [], []
    out = daemon.run_claude(cfg, paths, "해 줘", "sess-1", on_text=said.append, on_tool=tools.append)
    assert out == "다 됐습니다." and said == ["확인부터 할게요."] and tools == ["Bash"]


def test_run_claude_env_has_no_secrets(env, tmp_path, monkeypatch):
    cfg, paths = env
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "should-not-leak")
    cfg = dict(cfg, claude=fake_claude(tmp_path, """
        import os
        leak = os.environ.get("TELEGRAM_BOT_TOKEN")
        print(json.dumps({"type": "result", "is_error": False, "result": "leak=" + str(leak) + " agent=" + os.environ["JARVIS_HQ_AGENT"]}))
    """))
    out = daemon.run_claude(cfg, paths, "x", "s")
    assert out == "leak=None agent=Jarvis"


def test_run_claude_stall(env, tmp_path, monkeypatch):
    cfg, paths = env
    monkeypatch.setattr(daemon, "STALL", 1)
    cfg = dict(cfg, claude=fake_claude(tmp_path, "time.sleep(10)\n"))
    with pytest.raises(daemon.StallError):
        daemon.run_claude(cfg, paths, "x", "s")


def test_run_claude_error_result(env, tmp_path):
    cfg, paths = env
    cfg = dict(cfg, claude=fake_claude(tmp_path, """
        print(json.dumps({"type": "result", "is_error": True, "result": "한도"}))
        sys.exit(1)
    """))
    with pytest.raises(RuntimeError):
        daemon.run_claude(cfg, paths, "x", "s")


def test_live_first_phrase():
    said = []
    live = daemon.Live(said.append)
    live.tool("Read")
    live.tick(5)
    live.tick(daemon.LIVE_FIRST + 1)
    live.tick(daemon.LIVE_FIRST + 2)
    assert said == ["자료를 읽는 중이에요. 잠시만요."]



def test_end_to_end_through_real_messenger(env):
    """진짜 Messenger·Bot 에 가짜 HTTP 를 끼워: 받은 update → 해석 → 답 → sendMessage(HTML)."""
    import io
    cfg, paths = env
    sent = []

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=0):
        method = req.full_url.rsplit("/", 1)[-1]
        body = json.loads(req.data or b"{}")
        if method == "sendMessage":
            sent.append(body)
            return R(json.dumps({"ok": True, "result": {"message_id": 500 + len(sent)}}).encode())
        return R(json.dumps({"ok": True, "result": True}).encode())

    bot = telegram.Bot("9:tok", opener=opener, sleep=lambda s: None)
    msgr = telegram.Messenger(bot, cfg)
    dd = daemon.Daemon(cfg, paths, msgr, seal_key(cfg),
                       runner=lambda *a, **k: "**결과** 안녕하세요\n⟦작업용⟧\n세부")
    update = {"update_id": 10, "message": {"message_id": 3, "chat": {"id": 42}, "from": {"id": 42}, "text": "안녕"}}
    evs = msgr.parse(update)
    assert len(evs) == 1
    dd.handle_message(evs[0])
    assert sent and sent[-1]["chat_id"] == 42 and sent[-1]["parse_mode"] == "HTML"
    assert "<b>결과</b>" in sent[-1]["text"] and "blockquote expandable" in sent[-1]["text"]
