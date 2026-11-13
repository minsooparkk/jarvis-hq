"""메신저 층: Slack·Discord 를 가짜 HTTP·가짜 웹소켓으로. 받은 사건 꼴 → 대표 확인 → 승인 처리, 다른 사람의 눌림 거부,
긴 글 나누기, 받기 고리(ack·하트비트·닫힘 코드). 실제 Slack·Discord 에는 붙여 보지 않았다(docs/메신저-확인할-것.md).
(시험 속 id 는 개인정보 검사의 id 꼴에 걸리지 않게 일부러 짧은 가짜 글을 쓴다.)"""

import io
import json
import urllib.parse

import pytest

from conftest import seal_key
from jhq import cli, config, daemon, executor, messengers
from jhq.messengers import base, discord, slack, ws

OWNER_S, OTHER_S, DM_S = "UOWNER1", "UOTHER2", "DCHAN1"
XOXB, XAPP = "xox" + "b-test", "xap" + "p-test"  # 토큰 꼴 검사에 걸리지 않게 이어 붙인다
OWNER_D, OTHER_D, DM_D = "4242", "777", "9001"


class Resp(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status, self.headers = status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeHttp:
    """urlopen 대신. (방법, 주소 끝, 몸) 을 모으고 route(req) 가 준 답을 돌려준다."""

    def __init__(self, route):
        self.calls, self.route = [], route

    def __call__(self, req, timeout=0):
        url = req.full_url
        body = req.data or b""
        ctype = req.headers.get("Content-type", "")
        if "json" in ctype:
            parsed = json.loads(body or b"{}")
        elif "urlencoded" in ctype:
            parsed = dict(urllib.parse.parse_qsl(body.decode()))
        else:
            parsed = body
        self.calls.append((req.get_method(), url, parsed, dict(req.headers)))
        status, out = self.route(req.get_method(), url, parsed)
        return Resp(json.dumps(out).encode() if not isinstance(out, bytes) else out, status)

    def names(self):
        return [u.rsplit("/", 1)[-1] for _m, u, _b, _h in self.calls]


class FakeWS:
    """웹소켓 대신. frames 를 차례로 주고(None 은 시간 초과), 다 주면 닫힘(code)."""

    def __init__(self, frames, close_code=None):
        self.frames, self.sent, self.closed, self.close_code = list(frames), [], None, close_code

    def recv(self):
        if not self.frames:
            raise ws.Closed(self.close_code)
        f = self.frames.pop(0)
        return None if f is None else (f if isinstance(f, str) else json.dumps(f))

    def send(self, text):
        self.sent.append(json.loads(text))

    def close(self, code=1000):
        self.closed = code


# ---------- 공통 ----------

def test_registry_and_checks():
    assert messengers.kind({}) == "telegram" and messengers.kind({"messenger": "Slack"}) == "slack"
    with pytest.raises(messengers.NotReady):
        messengers.kind({"messenger": "kakao"})
    assert messengers.check_secret("slack-bot-token", XAPP) and not messengers.check_secret("slack-bot-token", XOXB)
    assert messengers.check_secret("discord-bot-token", "abc") and not messengers.check_secret("discord-bot-token", "a.b.c")
    cfg = {"messenger": "discord"}
    with pytest.raises(ValueError):
        messengers.set_owner(cfg, "이름")
    assert messengers.set_owner(cfg, OWNER_D) == OWNER_D and messengers.owner(cfg) == OWNER_D
    assert messengers.spec("slack")["packages"] and not messengers.spec("telegram")["packages"]


def test_split_fenced_keeps_code_blocks_whole():
    text = "앞\n```\n" + "\n".join(f"줄 {i}" for i in range(600)) + "\n```\n뒤"
    parts = base.split_fenced(text, 1900)
    assert len(parts) > 1 and all(len(p) <= 1900 for p in parts)
    for p in parts:
        assert sum(1 for ln in p.split("\n") if ln.strip().startswith("```")) % 2 == 0


# ---------- Slack ----------

def slack_route(method, url, body):
    name = url.rsplit("/", 1)[-1]
    if name == "conversations.open":
        return 200, {"ok": True, "channel": {"id": DM_S}}
    if name == "chat.postMessage":
        return 200, {"ok": True, "ts": f"5.{len(body.get('text', '')):06d}", "channel": DM_S}
    if name == "apps.connections.open":
        return 200, {"ok": True, "url": "wss://fake"}
    return 200, {"ok": True}


def make_slack(cfg, http=None, frames=None):
    http = http or FakeHttp(slack_route)
    conns = []

    def ws_connect(url):
        c = FakeWS(frames.pop(0) if frames else [])
        conns.append(c)
        return c
    api = slack.SlackApi(XOXB, XAPP, opener=http, sleep=lambda s: None, ws_connect=ws_connect)
    m = slack.SlackMessenger(api, dict(cfg, slack={"owner_id": OWNER_S, "team_id": "TEAM1"}))
    m.http, m.conns = http, conns
    return m


def im(user=OWNER_S, text="안녕", channel=DM_S, **extra):
    e = {"type": "message", "channel_type": "im", "user": user, "text": text, "ts": "6.000100", "channel": channel}
    e.update(extra)
    return {"type": "events_api", "envelope_id": "env-1", "payload": {"team_id": "TEAM1", "event_id": "Ev1", "event": e}}


def press(user=OWNER_S, ts="5.000010", value="b:0", channel=DM_S):
    return {"type": "interactive", "envelope_id": "env-2", "payload": {
        "type": "block_actions", "team": {"id": "TEAM1"}, "user": {"id": user}, "channel": {"id": channel},
        "container": {"type": "message", "message_ts": ts, "channel_id": channel}, "trigger_id": "tr",
        "actions": [{"action_id": value, "value": value, "action_ts": "1"}]}}


def test_slack_parse_only_owner_dm(env):
    cfg, _ = env
    m = make_slack(cfg)
    m.dm = DM_S
    ev = m.parse(im(text="a &amp; b &lt;x&gt;"))[0]
    assert ev["kind"] == "message" and ev["text"] == "a & b <x>" and ev["msg"] == "ts:6.000100" and ev["dm"]
    m.seen = []
    assert m.parse(im(user=OTHER_S)) == []                      # 다른 사람
    assert m.parse(im(channel="DOTHER")) == []                  # 대표 DM 밖
    assert m.parse(im(bot_id="B1")) == []                       # 봇 자신의 글
    assert m.parse(im(subtype="message_changed")) == []
    other_team = im()
    other_team["payload"]["team_id"] = "TEAM2"
    assert m.parse(other_team) == []
    assert m.parse(im()) and m.parse(im()) == []                # 다시 보낸 같은 사건은 한 번만
    f = im(text="", files=[{"url_private_download": "https://files.slack.com/x/a.pdf", "name": "a.pdf", "size": 3,
                            "mimetype": "application/pdf"}])
    f["payload"]["event_id"] = "Ev2"
    assert m.parse(f)[0]["file"]["id"].startswith("https://files.slack.com/")
    th = im(thread_ts="5.000005")
    th["payload"]["event_id"] = "Ev3"
    assert m.parse(th)[0]["reply_to"] == "ts:5.000005"


def test_slack_buttons_and_others_press(env):
    cfg, _ = env
    m = make_slack(cfg)
    m.dm = DM_S
    assert m.parse(press())[0] == {"kind": "button", "id": "tr", "chat": DM_S, "msg": "ts:5.000010", "index": 0}
    assert m.parse(press(user=OTHER_S, ts="2")) == []
    assert m.parse(press(channel="DOTHER", ts="3")) == []
    assert m.parse(press(value="R-0001|abc", ts="4")) == []  # 버튼 값에 승인 내용을 싣지 않는다


def test_slack_send_long_text_and_buttons(env):
    cfg, _ = env
    m = make_slack(cfg)
    m.send("dm", "**제목**\n" + "가나다라마바사 " * 1500 + "\n⟦작업용⟧\nR-0001", buttons=[("승인", "approve"), ("거부", "reject")])
    posts = [b for _m, u, b, _h in m.http.calls if u.endswith("chat.postMessage")]
    assert len(posts) > 2 and all(len(p["text"]) <= slack.TEXT_LIMIT for p in posts)
    assert all("blocks" not in p for p in posts[:-1])
    acts = posts[-1]["blocks"][-1]
    assert acts["type"] == "actions" and [e["value"] for e in acts["elements"]] == ["b:0", "b:1"]
    assert acts["elements"][0]["style"] == "primary" and acts["elements"][1]["style"] == "danger"
    assert posts[0]["text"].startswith("*제목*") and "_작업용_" in posts[-1]["text"]
    assert m.http.calls[0][3]["Authorization"] == "Bearer " + XOXB


def test_slack_mrkdwn():
    t = slack.to_mrkdwn("# 결과\n**굵게** a<b & [링크](https://example.com/x)\n```\n<그대로>\n```")
    assert t.startswith("*결과*") and "*굵게*" in t and "a&lt;b &amp;" in t and "<https://example.com/x|링크>" in t
    assert "&lt;그대로&gt;" in t


def test_slack_download_only_slack_host(env, tmp_path):
    cfg, _ = env
    m = make_slack(cfg, http=FakeHttp(lambda *a: (200, b"DATA")))
    p = m.download({"id": "https://files.slack.com/f/a.pdf", "name": "a.pdf"}, tmp_path)
    assert p.read_bytes() == b"DATA" and m.http.calls[-1][3]["Authorization"] == "Bearer " + XOXB
    with pytest.raises(ConnectionError):
        m.download({"id": "https://evil.example.com/a.pdf", "name": "a.pdf"}, tmp_path)


def test_slack_listen_acks_then_handles(env):
    cfg, _ = env
    frames = [[{"type": "hello"}, im(), None, {"type": "disconnect", "reason": "refresh_requested"}], [press()]]
    m = make_slack(cfg, frames=frames)
    got, stop = [], []

    def handler(ev):
        got.append(ev)
        if ev["kind"] == "button":
            stop.append(1)
    m.listen(handler, lambda part: None, stop=lambda: bool(stop))
    assert [e["kind"] for e in got] == ["message", "button"]
    assert m.conns[0].sent == [{"envelope_id": "env-1"}] and m.conns[1].sent == [{"envelope_id": "env-2"}]
    assert len(m.conns) == 2  # disconnect 뒤 새 주소로 다시 붙음


def run_approval(d, owner_press, stranger_press):
    """승인 요청 → 글·버튼 → 다른 사람 눌림(거부) → 대표 눌림(승인)."""
    paths = d.paths
    con = executor.connect(paths)
    n, _ = executor.new_request(paths, con, "hello", None, "안 함", {"summary": "시험", "why": "", "details": ""})
    con.close()
    d.flush_once()
    for ev in stranger_press():
        d.dispatch(ev) if ev["kind"] == "answer" else d.handle_button(ev)
    con = executor.connect(paths)
    assert executor.get(con, n)["state"] == "봉인"
    con.close()
    for ev in owner_press():
        d.handle_button(ev)
    con = executor.connect(paths)
    r = executor.get(con, n)
    con.close()
    return r


def test_slack_approval_end_to_end(env):
    cfg, paths = env
    m = make_slack(cfg)
    d = daemon.Daemon(cfg, paths, m, seal_key(cfg), runner=lambda *a, **k: "답")
    posted = []

    def route(method, url, body):
        if url.endswith("chat.postMessage") and body.get("blocks"):
            posted.append(body)
        return slack_route(method, url, body)
    m.http.route = route
    r = run_approval(d, lambda: m.parse(press(ts=f"5.{len(posted[0]['text']):06d}")),
                     lambda: m.parse(press(user=OTHER_S, ts=f"5.{len(posted[0]['text']):06d}")))
    assert posted and "승인 요청" in posted[0]["text"]
    assert r["state"] == "승인" and executor.sig_ok(d.key, r)
    upd = [b for _m, u, b, _h in m.http.calls if u.endswith("chat.update")]
    assert upd and upd[-1]["blocks"] == [] and "승인했습니다" in upd[-1]["text"]  # 결정 뒤 버튼을 거둠


# ---------- Discord ----------

def discord_route(method, url, body):
    path = url.split("/api/v10", 1)[-1]
    if path == "/users/@me/channels":
        return 200, {"id": DM_D}
    if path.startswith(f"/channels/{DM_D}/messages") and method == "POST":
        return 200, {"id": str(5000 + len(body.get("content", "")))}
    if path == "/gateway/bot":
        return 200, {"url": "wss://gw"}
    if path == "/users/@me":
        return 200, {"username": "jarvisbot"}
    return 204, b""


def make_discord(cfg, http=None, frames=None):
    http = http or FakeHttp(discord_route)
    conns = []

    def ws_connect(url):
        c = FakeWS(frames.pop(0) if frames else [], close_code=4004 if not frames else None)
        c.url = url
        conns.append(c)
        return c
    api = discord.DiscordApi("a.b.c", opener=http, sleep=lambda s: None, ws_connect=ws_connect)
    m = discord.DiscordMessenger(api, dict(cfg, discord={"owner_id": OWNER_D}))
    m.http, m.conns = http, conns
    return m


def dmsg(author=OWNER_D, content="안녕", channel=DM_D, **extra):
    d = {"id": "11", "channel_id": channel, "author": {"id": author, "username": "u"}, "content": content}
    d.update(extra)
    return d


def click(user=OWNER_D, msg="5001", custom="b:0", channel=DM_D, guild=None):
    d = {"type": 3, "id": "i1", "token": "tok", "channel_id": channel, "data": {"custom_id": custom, "component_type": 2},
         "message": {"id": msg}, "user": {"id": user}}
    if guild:
        d["guild_id"], d["member"] = guild, {"user": d.pop("user")}
    return d


def test_discord_parse_only_owner_dm(env):
    cfg, _ = env
    m = make_discord(cfg)
    m.dm = DM_D
    ev = m.parse("MESSAGE_CREATE", dmsg(message_reference={"message_id": "77"}))[0]
    assert ev == {"kind": "message", "chat": int(DM_D), "msg": 11, "topic": None, "topic_name": None, "dm": True,
                  "text": "안녕", "reply_to": 77}
    assert m.parse("MESSAGE_CREATE", dmsg(author=OTHER_D)) == []
    assert m.parse("MESSAGE_CREATE", dmsg(guild_id="1")) == []        # 서버 글
    assert m.parse("MESSAGE_CREATE", dmsg(channel="1")) == []         # 대표 DM 밖
    bot = dmsg()
    bot["author"]["bot"] = True
    assert m.parse("MESSAGE_CREATE", bot) == []
    voice = dmsg(content="", flags=8192, attachments=[{"url": "https://cdn.discordapp.com/a.ogg", "filename": "v.ogg",
                                                       "size": 9, "content_type": "audio/ogg"}])
    assert m.parse("MESSAGE_CREATE", voice)[0]["file"]["kind"] == "voice"


def test_discord_buttons_and_others_press(env):
    cfg, _ = env
    m = make_discord(cfg)
    m.dm = DM_D
    assert m.parse("INTERACTION_CREATE", click())[0] == {"kind": "button", "id": "i1:tok", "chat": int(DM_D), "msg": 5001,
                                                           "index": 0}
    for d in (click(user=OTHER_D), click(guild="1"), click(channel="1")):
        assert m.parse("INTERACTION_CREATE", d) == [{"kind": "answer", "id": "i1:tok", "text": "권한이 없습니다."}]
    m.answer("i1:tok", "권한이 없습니다.")
    meth, url, body, _h = m.http.calls[-1]
    assert url.endswith("/interactions/i1/tok/callback") and body == {"type": 4, "data": {"content": "권한이 없습니다.", "flags": 64}}
    m.answer("i1:tok", "받았습니다.")
    assert m.http.calls[-1][2] == {"type": 6}


def test_discord_send_long_and_components(env):
    cfg, _ = env
    m = make_discord(cfg)
    m.send("dm", "가" * 4500, buttons=[("승인", "approve"), ("수정", "revise"), ("거부", "reject")], reply_to=3)
    posts = [b for meth, u, b, _h in m.http.calls if u.endswith(f"/channels/{DM_D}/messages") and meth == "POST"]
    assert len(posts) == 3 and all(len(p["content"]) <= 2000 for p in posts)
    assert posts[0]["message_reference"]["message_id"] == "3" and "components" not in posts[0]
    row = posts[-1]["components"][0]["components"]
    assert [b["custom_id"] for b in row] == ["b:0", "b:1", "b:2"] and [b["style"] for b in row] == [3, 2, 4]
    assert all(len(b["custom_id"]) <= 100 for b in row)
    assert posts[0]["allowed_mentions"] == {"parse": []}
    h = m.http.calls[-1][3]
    assert h["Authorization"] == "Bot a.b.c" and h["User-agent"].startswith("DiscordBot (")


def test_discord_rate_limit_retry(env):
    cfg, _ = env
    seq = [(429, {"retry_after": 0.01}), (200, {"id": "5"})]
    http = FakeHttp(lambda meth, url, body: (200, {"id": DM_D}) if url.endswith("/users/@me/channels") else seq.pop(0))
    m = make_discord(cfg, http=http)
    assert m.send("dm", "a") == (int(DM_D), 5)


def test_discord_approval_end_to_end(env):
    cfg, paths = env
    m = make_discord(cfg)
    d = daemon.Daemon(cfg, paths, m, seal_key(cfg), runner=lambda *a, **k: "답")

    def approval_msg():
        for meth, u, b, _h in m.http.calls:
            if meth == "POST" and u.endswith("/messages") and b.get("components"):
                return str(5000 + len(b["content"]))
    m.dm = DM_D
    r = run_approval(d, lambda: m.parse("INTERACTION_CREATE", click(msg=approval_msg())),
                     lambda: m.parse("INTERACTION_CREATE", click(user=OTHER_D, msg=approval_msg())))
    assert r["state"] == "승인" and executor.sig_ok(d.key, r)
    cb = [b for meth, u, b, _h in m.http.calls if u.endswith("/callback")]
    assert cb[0]["type"] == 4 and cb[0]["data"]["flags"] == 64 and cb[-1] == {"type": 6}  # 남에게는 거절, 대표에게는 받음
    patch = [b for meth, u, b, _h in m.http.calls if meth == "PATCH"]
    assert patch and patch[-1]["components"] == [] and "승인했습니다" in patch[-1]["content"]


def test_discord_gateway_identify_heartbeat_and_fatal_close(env, monkeypatch):
    cfg, _ = env
    monkeypatch.setattr(discord.random, "random", lambda: 0.0)
    hello = {"op": 10, "d": {"heartbeat_interval": 41250}}
    ready = {"op": 0, "s": 1, "t": "READY", "d": {"session_id": "S1", "resume_gateway_url": "wss://resume",
                                                  "user": {"id": "999"}}}
    msg = {"op": 0, "s": 2, "t": "MESSAGE_CREATE", "d": dmsg()}
    frames = [[hello, {"op": 11}, ready, msg, {"op": 7}], [hello, {"op": 11}]]
    m = make_discord(cfg, frames=frames)
    got = []
    with pytest.raises(discord.Fatal):
        m.listen(got.append, lambda part: None)
    first, second = m.conns[0], m.conns[1]
    ident = [s for s in first.sent if s["op"] == 2][0]
    assert ident["d"]["intents"] == 4096 and ident["d"]["token"] == "a.b.c"  # DM 만(메시지 내용 intent 없음)
    assert any(s["op"] == 1 for s in first.sent)  # 하트비트
    assert [e["kind"] for e in got] == ["message"]
    assert second.url.startswith("wss://resume") and [s for s in second.sent if s["op"] == 6][0]["d"]["seq"] == 2


# ---------- 명령 ----------

def test_cli_messenger_status_and_set_owner(env, capsys):
    cfg, _ = env
    assert cli.main(["messenger", "status"]) == 1  # 텔레그램 토큰 없음
    assert "텔레그램" in capsys.readouterr().out
    assert cli.main(["slack", "set-owner", "uowner1"]) == 0
    assert config.load()["slack"]["owner_id"] == "UOWNER1"
    assert cli.main(["telegram", "set-owner", "42"]) == 0  # 예전 명령은 메신저 명령으로 넘어감
    assert config.load()["telegram"]["owner_id"] == 42
    assert cli.main(["discord", "set-owner", "이름"]) == 2


def test_ws_wrapper_with_fake_module(monkeypatch):
    """websocket-client 를 흉내 낸 모듈로 한 겹(ws.Conn)의 프레임 처리를 본다(실제 패키지는 Slack·Discord 설치에만 받는다)."""
    import struct
    import sys
    import types

    class TimeoutE(Exception):
        pass

    class ClosedE(Exception):
        pass

    class Frame:
        def __init__(self, data):
            self.data = data

    class W:
        def __init__(self, seq):
            self.seq, self.ponged, self.sent = list(seq), [], []

        def recv_data_frame(self, control):
            item = self.seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        def pong(self, data):
            self.ponged.append(data)

        def send(self, t):
            self.sent.append(t)

        def close(self, status=1000):
            pass

    abnf = types.SimpleNamespace(OPCODE_TEXT=1, OPCODE_BINARY=2, OPCODE_CLOSE=8, OPCODE_PING=9)
    fake = types.SimpleNamespace(ABNF=abnf, WebSocketTimeoutException=TimeoutE, WebSocketConnectionClosedException=ClosedE,
                                 WebSocketException=Exception)
    w = W([(1, Frame("안녕".encode())), TimeoutE(), (9, Frame(b"p")), (8, Frame(struct.pack("!H", 4004) + b"auth"))])
    fake.create_connection = lambda url, timeout=5, enable_multithread=True: w
    monkeypatch.setitem(sys.modules, "websocket", fake)
    c = ws.connect("wss://x")
    assert c.recv() == "안녕" and c.recv() is None and c.recv() is None and w.ponged == [b"p"]
    with pytest.raises(ws.Closed) as e:
        c.recv()
    assert e.value.code == 4004
