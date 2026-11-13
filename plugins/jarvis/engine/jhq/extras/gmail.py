"""선택 모듈: Gmail 로 보내기(공식 API). 보내기는 실행기 대상 'gmail-send' 로만 돈다(대표 승인 뒤 한 번).

준비(대표가 한 번, 자기 맥에서):
  1. Google Cloud 에서 OAuth 클라이언트(데스크톱 앱)를 만들고 Gmail API 를 켠다.
  2. 터미널: `jarvis secret set gmail-client-id` · `jarvis secret set gmail-client-secret`
  3. 터미널: `jarvis mail auth` (브라우저가 열리면 보낼 계정으로 허락 → 갱신 토큰이 키체인에 들어감)
  4. <홈>/hooks/targets.yaml 의 gmail-send 대상 주석을 푼다.

  jarvis mail status                         연결 준비 상태(값은 안 보임)
  jarvis mail request --to 주소 --subject 제목 --body-file 파일 [--cc 주소] [--reply-to 메시지ID --thread-id 스레드ID]
                      --if-rejected "…" --결론 "…" [--배경 "…" --본문 "…"]
  (실행기 전용) python -m jhq.extras.gmail send     $JARVIS_PAYLOAD 의 봉인된 메일을 보낸다
"""

import argparse
import base64
import http.server
import json
import os
import re
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from .. import config, executor, secrets

CLIENT_ID, CLIENT_SECRET, REFRESH = "gmail-client-id", "gmail-client-secret", "gmail-refresh-token"
SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
TARGET = "gmail-send"
ADDR = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def ready(cfg=None):
    return {n: secrets.has(n, cfg) for n in (CLIENT_ID, CLIENT_SECRET, REFRESH)}


def build_payload(to, subject, body, cc=None, reply_to=None, thread_id=None):
    for a in [to] + list(cc or []):
        if not ADDR.match(a or ""):
            raise executor.ExecError(f"메일 주소 모양이 아닙니다: {a}")
    if re.match(r"\s*(re|회신|답장)\s*:", subject or "", re.I) and not (reply_to or thread_id):
        raise executor.ExecError("답장 제목(Re:)인데 --reply-to 나 --thread-id 가 없어 새 메일로 나갑니다. "
                                 "원래 메일의 메시지 ID(<…@…>)와 스레드 ID 를 넣거나, 새 메일이면 제목에서 Re: 를 빼세요.")
    if not str(body or "").strip():
        raise executor.ExecError("본문이 비었습니다")
    p = {"to": to, "cc": list(cc or []), "subject": subject, "body": body}
    if reply_to:
        p["in_reply_to"] = reply_to
    if thread_id:
        p["thread_id"] = thread_id
    return p


def mime(p):
    m = EmailMessage()
    m["To"] = p["to"]
    if p.get("cc"):
        m["Cc"] = ", ".join(p["cc"])
    m["Subject"] = p["subject"]
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid()
    if p.get("in_reply_to"):
        m["In-Reply-To"] = p["in_reply_to"]
        m["References"] = p["in_reply_to"]
    m.set_content(p["body"])
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


def access_token(cfg=None, opener=urllib.request.urlopen):
    vals = {n: secrets.get(n, cfg) for n in (CLIENT_ID, CLIENT_SECRET, REFRESH)}
    if not all(vals.values()):
        raise RuntimeError("Gmail 연결이 준비되지 않았습니다(jarvis mail status)")
    body = urllib.parse.urlencode({"client_id": vals[CLIENT_ID], "client_secret": vals[CLIENT_SECRET],
                                   "refresh_token": vals[REFRESH], "grant_type": "refresh_token"}).encode()
    with opener(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
        return json.loads(r.read())["access_token"]


def send(payload_path, cfg=None, opener=urllib.request.urlopen):
    p = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    req = {"raw": mime(p)}
    if p.get("thread_id"):
        req["threadId"] = p["thread_id"]
    tok = access_token(cfg, opener)
    r = urllib.request.Request(SEND_URL, data=json.dumps(req).encode(),
                               headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with opener(r, timeout=60) as resp:
        out = json.loads(resp.read())
    return out.get("id")


def auth(cfg=None, port=0):
    """브라우저 로그인으로 갱신 토큰을 받아 키체인에 넣는다(대표가 자기 맥에서)."""
    cid, csec = secrets.get(CLIENT_ID, cfg), secrets.get(CLIENT_SECRET, cfg)
    if not cid or not csec:
        print("먼저 터미널에서: jarvis secret set gmail-client-id · jarvis secret set gmail-client-secret", file=sys.stderr)
        return 2
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got["code"] = (q.get("code") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("허락을 받았습니다. 이 창은 닫아도 됩니다.".encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    redirect = f"http://127.0.0.1:{srv.server_port}/"
    url = AUTH_URL + "?" + urllib.parse.urlencode({"client_id": cid, "redirect_uri": redirect, "response_type": "code",
                                                    "scope": SCOPE, "access_type": "offline", "prompt": "consent"})
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    webbrowser.open(url)
    print("브라우저에서 보낼 계정으로 허락해 주세요(3분 기다림).")
    t.join(180)
    srv.server_close()
    if not got.get("code"):
        print("허락을 받지 못했습니다.", file=sys.stderr)
        return 1
    body = urllib.parse.urlencode({"code": got["code"], "client_id": cid, "client_secret": csec,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
        tok = json.loads(r.read())
    if not tok.get("refresh_token"):
        print("갱신 토큰이 오지 않았습니다. 다시 해 보세요.", file=sys.stderr)
        return 1
    secrets.put(REFRESH, tok["refresh_token"], cfg)
    print("Gmail 보내기 연결을 마쳤습니다(키체인에 저장, 값은 찍지 않음).")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jarvis mail", description="Gmail 보내기(실행기 승인으로만)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("auth")
    q = sub.add_parser("request", help="메일 한 통 보내기 요청(=승인 요청)")
    q.add_argument("--to", required=True)
    q.add_argument("--cc", action="append")
    q.add_argument("--subject", required=True)
    q.add_argument("--body-file", required=True)
    q.add_argument("--reply-to", help="답장할 원래 메일의 Message-ID(<…@…>)")
    q.add_argument("--thread-id", help="Gmail 스레드 ID(답장일 때)")
    q.add_argument("--if-rejected", required=True)
    for ko, en, h, limit in executor.PLAIN_FIELDS:
        q.add_argument(f"--{ko}", f"--{en}", dest=en, default="", help=f"{h} ({limit}자까지)")
    sub.add_parser("send", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    cfg = config.load()
    paths = config.Paths(cfg)
    try:
        if a.cmd == "status":
            r = ready(cfg)
            for k, v in r.items():
                print(f"{k}: {'있음' if v else '없음'}")
            has_target = TARGET in executor.load_targets(paths)
            print(f"실행 대상 {TARGET}: {'있음' if has_target else '없음(hooks/targets.yaml 주석 풀기)'}")
            return 0 if all(r.values()) and has_target else 1
        if a.cmd == "auth":
            return auth(cfg)
        if a.cmd == "send":
            src = os.environ.get("JARVIS_PAYLOAD")
            if not src or not os.environ.get("JARVIS_REQUEST_ID"):
                print("실행기 전용 입구입니다(승인된 요청에서만).", file=sys.stderr)
                return 2
            print("보냄: " + str(send(src, cfg)))
            return 0
        body = Path(a.body_file).expanduser().read_text(encoding="utf-8")
        p = build_payload(a.to, a.subject, body, a.cc, a.reply_to, a.thread_id)
        draft_dir = paths.work / "mail"
        draft_dir.mkdir(parents=True, exist_ok=True)
        f = draft_dir / f"mail-{config.now(cfg):%Y%m%d-%H%M%S}.json"
        f.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
        cols = executor.plain_from(a.summary or f"메일 「{a.subject}」 을 {a.to} 에게 보냅니다", a.why, a.details or body[:900])
        con = executor.connect(paths)
        try:
            _, msg = executor.new_request(paths, con, TARGET, str(f), a.if_rejected, cols,
                                          actor=os.environ.get("JARVIS_HQ_AGENT") or "터미널")
        finally:
            con.close()
        print(msg)
        return 0
    except executor.ExecError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(["send"] if len(sys.argv) > 1 and sys.argv[1] == "send" else sys.argv[1:]))
