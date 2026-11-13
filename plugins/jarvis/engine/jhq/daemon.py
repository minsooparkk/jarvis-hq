"""jarvisd: 메신저(텔레그램·Slack·Discord) ↔ 에이전트(Claude Code 또는 Codex) 세션 데몬. 서비스로 뜬다(맥 launchd · 윈도 작업 스케줄러, <label_prefix>.jarvisd).

하는 일
- 대표 DM(과 선택한 그룹 토픽)의 말을 받아 Jarvis 홈에서 에이전트(`claude -p` 또는 `codex exec`, jhq.agents)를 돌리고 답을 올린다.
  DM 은 하루 한 대화(같은 날은 이어 감), 그룹의 토픽은 토픽마다 대화 하나.
- 진행 표시: Jarvis 가 도구 사이에 쓴 짧은 글을 그때그때 올리고, 20초 동안 말이 없으면 '…중이에요. 잠시만요.' 한 줄.
- 답을 만드는 동안 대표가 더 말하면 따로 답하지 않고 '말씀 받았습니다' 한 줄 뒤 지금 만드는 답에 합친다.
- 승인 요청(실행기 장부의 '봉인' 요청)이 생기면 대표 DM 에 버튼(승인·수정·거부)과 함께 올린다. 승인은 서명해 장부에 적는다.
- 보낼 글 대기열(outbox)을 몇 초마다 올린다. schedule.yaml 의 예약(지시·스크립트·승인묶음)을 정시에 돌린다.
- 심장박동 파일을 적는다(지킴이가 본다).

Agent(claude·codex)에게는 메신저 토큰과 서명 열쇠를 넘기지 않는다. 대표가 아닌 사람의 말·버튼은 무시한다.
메신저마다 다른 것(보내기·받기·버튼·서식)은 jhq.messengers 가 맡는다.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

import yaml

from . import agents, config, cronlib, executor, messengers, outbox, plain, secrets

log = logging.getLogger("jarvisd")

STALL = agents.STALL  # 이 안에 에이전트가 한 줄도 내지 않으면 '시작 못 함'
LIVE_FIRST = 20      # 이 안에 한 마디도 없으면 '…중이에요. 잠시만요.'
PROGRESS_EVERY = 300  # 오래 걸리면 이 간격으로 '아직 하는 중'
FAIL_REPEAT = 6 * 3600
STRIP_ENV = agents.base.STRIP_ENV
HELP = ("명령(DM): /상태 · /승인(결정 안 한 승인 다시 알림) · /new(오늘 대화 새로) · /stop(만들던 답 멈춤) · /도움\n"
        "(/ 없이 한 낱말로 '상태'·'승인'·'새로'·'멈춰'·'도움' 도 됩니다)\n"
        "그 밖의 말은 Jarvis 가 읽고 답합니다. 사진·파일을 보내면 받아서 봅니다.")
COMMANDS = {"/stop": "stop", "stop": "stop", "/new": "new", "/reset": "new", "/start": "start", "/상태": "status",
            "/status": "status", "/승인": "approvals", "/approvals": "approvals", "/도움": "help", "/help": "help"}
BARE = {"상태": "status", "승인": "approvals", "도움": "help", "새로": "new", "멈춰": "stop"}  # 한 낱말만(Slack 은 / 를 가로챔)
TOOL_PHRASE = {"Bash": "확인하는 중", "Read": "자료를 읽는 중", "Grep": "자료를 찾는 중", "Glob": "자료를 찾는 중",
               "Edit": "파일을 고치는 중", "Write": "파일을 쓰는 중", "apply_patch": "파일을 고치는 중", "WebFetch": "웹에서 찾는 중", "WebSearch": "웹에서 찾는 중",
               "Agent": "맡긴 일을 기다리는 중", "Task": "맡긴 일을 기다리는 중"}
BUTTONS = [("승인", "approve"), ("수정", "revise"), ("거부", "reject")]
DECIDED = {"승인됨": "✅ 승인했습니다", "거부됨": "❌ 거부했습니다", "수정 요청": "✏️ 수정을 요청했습니다"}


def style_hint(cfg, where="텔레그램"):
    owner = cfg.get("owner_title") or "대표"
    return (f"네 답은 그대로 {owner}의 {where}에 올라간다. 휴대폰에서 읽기 좋게 짧게, 결과부터 쓴다. 표 대신 짧은 목록. "
            f"도구를 써야 하는 답이면 첫 도구 전에 '○○부터 볼게요' 한 줄, 단계가 끝날 때마다 도구 호출 사이에 한두 문장을 쓴다"
            f"(그 글은 그 자리에서 따로 올라간다). 마지막 답은 결과 정리만. 경로·명령·오류 원문이 꼭 필요하면 맨 끝에 "
            f"'{plain.WORK}' 한 줄을 두고 그 아래에 적는다(접혀서 올라간다). "
            f"답을 만드는 동안 {owner}이(가) 더 말하면 '[덧붙임]' 으로 들어온다. 한 답에 반영한다. "
            f"'[파일 첨부: 경로]' 줄이 있으면 그 파일을 열어 본 뒤 답한다. "
            f"보여 줄 그림·파일은 `jarvis notify dm \"설명\" --file 경로` 로 올린다. "
            f"되돌릴 수 없는 일(발송·배포·결제·영구 삭제·공개 게시)은 `jarvis exec request`(승인 버튼)로만 한다.")


StallError = agents.StallError


def agent_env(cfg):
    return agents.agent_env(cfg)


def run_agent(cfg, paths, prompt, session, resume=False, context="", timeout=None, on_text=None, on_tool=None,
              on_tick=None, register=None):
    """설정한 에이전트(config agent: claude · codex)로 답을 만든다. 마지막 답(Reply, .session 에 실제 대화 id)."""
    return agents.get(cfg).run(cfg, paths, prompt, session, resume, context, timeout, on_text, on_tool, on_tick, register,
                               stall=STALL)


def run_claude(cfg, paths, prompt, session, resume=False, context="", timeout=None, on_text=None, on_tool=None,
               on_tick=None, register=None):
    """claude -p 를 stream-json 으로 돌려 최종 답을 돌려준다(예전 이름. jhq.agents.claude)."""
    return agents.get("claude").run(cfg, paths, prompt, session, resume, context, timeout, on_text, on_tool, on_tick,
                                    register, stall=STALL)


class Live:
    """답을 만드는 동안 진행을 따로따로 올린다(고치거나 지우지 않음)."""

    def __init__(self, post):
        self.post, self.said, self.waited, self.last_tool, self.next_progress = post, 0, False, "", PROGRESS_EVERY

    def text(self, t):
        self.post(t)
        self.said += 1

    def tool(self, name):
        self.last_tool = name

    def phrase(self):
        if self.last_tool.startswith("mcp__"):
            return "자료를 찾는 중"
        return TOOL_PHRASE.get(self.last_tool, "시작하는 중" if not self.last_tool else "확인하는 중")

    def tick(self, el):
        if not self.said and not self.waited and el >= LIVE_FIRST:
            self.waited = True
            self.post(f"{self.phrase()}이에요. 잠시만요.")
        if el >= self.next_progress:
            self.next_progress += PROGRESS_EVERY
            self.post(f"아직 하는 중이에요({el / 60:.0f}분째). 지금은 {self.phrase()}.")


class Daemon:
    def __init__(self, cfg, paths, msgr, key, runner=None):
        self.cfg, self.paths, self.msgr, self.key, self.runner = cfg, paths.ensure(), msgr, key, runner or run_agent
        try:
            self.agent = agents.kind(cfg)
        except agents.UnknownAgent:
            self.agent = "claude"
        self.state_lock, self.talk_lock, self.approval_lock = threading.Lock(), threading.Lock(), threading.Lock()
        self.session_locks, self.talks, self.running, self.job_fail = {}, {}, {}, {}
        self.started = time.time()

    # ----- 상태 파일 -----
    def load_state(self):
        try:
            return json.loads(self.paths.daemon_state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"sessions": {}, "jobs": {}, "checked": None}

    def save_state(self, st):
        config.write_atomic(self.paths.daemon_state, json.dumps(st, ensure_ascii=False, indent=1))

    def beat(self, part):
        try:
            try:
                hb = json.loads(self.paths.heartbeat.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                hb = {}
            hb[part] = time.time()
            config.write_atomic(self.paths.heartbeat, json.dumps(hb))
        except OSError:
            pass

    def skey(self, key):
        """상태 파일의 대화 열쇠. 에이전트마다 대화 id 가 달라 Claude 가 아니면 앞에 이름을 붙인다(바꿔도 옛 대화를 잇지 않음)."""
        return key if self.agent == "claude" else f"{self.agent}/{key}"

    def session_for(self, key):
        with self.state_lock:
            st = self.load_state()
            sess = st["sessions"].get(self.skey(key))
            if sess:
                return sess, True
            sess = st["sessions"][self.skey(key)] = str(uuid.uuid4())
            self.save_state(st)
            return sess, False

    def bind_session(self, key, old, new):
        """에이전트가 스스로 정한 대화 id(Codex)를 그 대화의 id 로 적는다."""
        if not new or new == old:
            return
        with self.state_lock:
            st = self.load_state()
            if st["sessions"].get(self.skey(key)) in (old, None):
                st["sessions"][self.skey(key)] = new
                self.save_state(st)

    def owner(self):
        return self.cfg.get("owner_title") or "대표"

    def where(self):
        return getattr(self.msgr, "display", "텔레그램")

    def alerts(self):
        return "긴급" if "긴급" in self.msgr.topics else "dm"

    def say(self, dest, text, reply_to=None):
        try:
            return self.msgr.send(dest, text, reply_to=reply_to)
        except Exception:  # noqa: BLE001
            log.exception("글 올리기 실패 %s", dest)
            return None

    # ----- 대화 -----
    def talk_begin(self, key, text):
        with self.talk_lock:
            t = self.talks.setdefault(key, {"busy": False, "extra": []})
            if t["busy"]:
                t["extra"].append(text)
                return False
            t["busy"] = True
            return True

    def talk_more(self, key, done=False):
        with self.talk_lock:
            t = self.talks.setdefault(key, {"busy": False, "extra": []})
            extra, t["extra"] = t["extra"], []
            if not extra or done:
                t["busy"] = False
            return extra

    def merge_prompt(self, extra, answer):
        said = "\n".join("- " + t for t in extra)
        return (f"[덧붙임 · {config.now(self.cfg):%H:%M}] 네가 답을 만드는 동안 {self.owner()}이(가) 이렇게 더 말했다:\n{said}\n\n"
                f"방금 만든 답(아직 보내지 않았다):\n{answer}\n\n"
                "덧붙인 말까지 반영해 답 하나로 다시 쓴다. 이미 한 일은 다시 하지 않는다. 답만 쓴다.")

    def answer(self, key, prompt, resume_key_session, context, dest, reply_to=None):
        sess, resume = resume_key_session
        live = Live(lambda t: self.say(dest, t, reply_to))
        try:
            out = self.runner(self.cfg, self.paths, prompt, sess, resume, context, on_text=live.text, on_tool=live.tool,
                              on_tick=live.tick, register=lambda p: self.running.__setitem__(key, p))
            self.bind_session(key, sess, getattr(out, "session", None))
            return out
        except Exception as e:  # noqa: BLE001
            if not resume:  # 새로 시작한 대화가 실패하면 다음 말은 새 대화로(없는 세션을 이어 가려다 또 실패하지 않게)
                with self.state_lock:
                    st = self.load_state()
                    if st["sessions"].get(self.skey(key)) == sess:
                        st["sessions"].pop(self.skey(key), None)
                        self.save_state(st)
            if isinstance(e, StallError):
                return f"답을 만들지 못했습니다. {e}"
            log.exception("답 만들기 실패 %s", key)
            return f"답을 만들지 못했습니다. 이유: {str(e)[:300]}"
        finally:
            self.running.pop(key, None)

    def converse(self, key, ev, text, prompt, context, dest, reply_to=None):
        self.msgr.react(ev["chat"], ev["msg"], True)
        if not self.talk_begin(key, text):
            self.say(dest, "말씀 받았습니다. 지금 만드는 답에 같이 반영합니다.", reply_to)
            return
        try:
            with self.session_locks.setdefault(key, threading.Lock()):
                self.msgr.typing(dest)
                sess = self.session_for(key)
                ans = self.answer(key, prompt, sess, context, dest, reply_to)
                sid = getattr(ans, "session", None) or sess[0]  # Codex 는 첫 답에서 대화 id 가 정해진다
                while True:
                    extra = self.talk_more(key)
                    if not extra:
                        break
                    ans = self.answer(key, self.merge_prompt(extra, ans), (sid, True), context, dest, reply_to)
                if ans and not plain.quiet(ans):
                    self.say(dest, ans, reply_to)
                with self.state_lock:
                    st = self.load_state()
                    st["last_reply_at"] = config.stamp(self.cfg)
                    self.save_state(st)
        finally:
            dropped = self.talk_more(key, done=True)
            if dropped:
                self.say(dest, f"덧붙인 말 {len(dropped)}개를 반영하지 못했습니다. 다시 보내 주세요.", reply_to)
            self.msgr.react(ev["chat"], ev["msg"], False)

    def handle_message(self, ev):
        text = (ev.get("text") or "").strip()
        if ev.get("reply_to"):
            con = outbox.connect(self.paths)
            try:
                row = outbox.post_of(con, ev["chat"], ev["reply_to"])
            finally:
                con.close()
            if row and row["kind"] == "revise":
                return self.finish_revise(row, text)
        if ev["dm"] and text:
            words = text.split()
            first = words[0].split("@")[0]
            cmd = COMMANDS.get(first) or (BARE.get(first) if len(words) == 1 else None)
            if cmd:
                return self.command(cmd)
        if ev.get("file"):
            text = (text + "\n" + self.receive_file(ev["file"])).strip()
        if not text:
            return None
        now = config.now(self.cfg)
        stamp = f"{now:%Y-%m-%d %H:%M}"
        hint = style_hint(self.cfg, self.where())
        if ev["dm"]:
            key = f"dm-{now:%Y-%m-%d}"
            prompt = f"[{self.cfg.get('assistant_name') or 'Jarvis'} DM · {self.owner()} · {stamp}]\n{text}"
            return self.converse(key, ev, text, prompt, f"이 대화는 {self.where()} DM 이다. " + hint, "dm")
        topic = ev.get("topic") or 0
        name = ev.get("topic_name") or f"토픽 {topic}"
        key = f"topic-{topic}"
        prompt = f"[그룹 '{name}' 토픽에서 {self.owner()} · {stamp}]\n{text}"
        ctx = f"이 대화는 텔레그램 그룹의 '{name}' 토픽이다. 이 토픽만의 대화가 이어지고 DM·다른 토픽과 동시에 돈다. " + hint
        return self.converse(key, ev, text, prompt, ctx, (ev["chat"], topic or None), reply_to=ev["msg"])

    def receive_file(self, f):
        limit = getattr(self.msgr, "max_file", 20 * 1024 * 1024)
        if int(f.get("size") or 0) > limit:
            return f"[파일 첨부 실패: {limit // 2**20}MB 를 넘어 받지 못함]"
        try:
            day = config.now(self.cfg).strftime("%Y-%m-%d")
            p = self.msgr.download(f, self.paths.inbox / day)
        except Exception as e:  # noqa: BLE001
            return f"[파일 첨부 실패: {str(e)[:120]}]"
        kind = "사진" if f["kind"] == "photo" else "음성" if f["kind"] in ("voice", "audio") else "파일"
        note = " (음성은 글로 바뀌지 않았다. 받아쓰기는 스킬 transcribe)" if kind == "음성" else ""
        return f"[{kind} 첨부: {p}]{note}"

    def command(self, cmd):
        if cmd == "stop":
            procs = [p for k, p in list(self.running.items()) if k.startswith("dm-")]
            for p in procs:
                p.jarvis_stopped = True  # 윈도에는 신호가 없어 종료 코드로 알 수 없다
                config.plat().terminate(p)
            self.say("dm", "멈췄습니다." if procs else "지금 돌고 있는 답이 없습니다.")
        elif cmd == "new":
            with self.state_lock:
                st = self.load_state()
                st["sessions"].pop(self.skey(f"dm-{config.now(self.cfg):%Y-%m-%d}"), None)
                self.save_state(st)
            self.say("dm", "오늘 대화를 새로 시작합니다. 앞 대화는 이어 가지 않습니다.")
        elif cmd == "start":
            self.say("dm", f"{self.cfg.get('assistant_name') or 'Jarvis'}입니다. 여기에 말씀하시면 됩니다.\n" + HELP)
        elif cmd == "help":
            self.say("dm", HELP)
        elif cmd == "status":
            self.say("dm", self.status_text())
        elif cmd == "approvals":
            n = self.approval_bundle("지금")
            self.say("dm", f"승인 기다리는 건 {n}건입니다. 처음 올린 글의 버튼이 그대로 먹습니다." if n else "승인 대기 중인 건이 없습니다.")

    def status_text(self):
        st = self.load_state()
        lines = [f"**상태 · {config.now(self.cfg):%m-%d %H:%M}**",
                 f"켜진 지 {(time.time() - self.started) / 3600:.1f}시간 · 답 만드는 중 {len(self.running)}건 · "
                 f"예약 점검 {str(st.get('checked') or '')[11:16] or '?'}"]
        try:
            econ = executor.connect(self.paths)
            try:
                waiting = len(executor.pending_approvals(econ))
                queued = econ.execute("select count(*) from requests where state in ('승인','실행 중')").fetchone()[0]
            finally:
                econ.close()
            lines.append(f"승인 기다리는 요청 {waiting}건 · 실행 기다리는 요청 {queued}건"
                         + (" · 실행기 멈춤 상태" if self.paths.pause.exists() else ""))
        except Exception as e:  # noqa: BLE001
            lines.append(f"실행 요청 확인 실패: {str(e)[:80]}")
        if self.job_fail:
            lines.append("실패 중인 예약: " + ", ".join(f"{k}({v['n']}회)" for k, v in self.job_fail.items()))
        try:
            free = shutil.disk_usage(str(self.paths.home)).free // 2**30
            lines.append(f"디스크 여유 {free}GB" + (" ⚠️" if free < 20 else ""))
        except OSError:
            pass
        return "\n".join(lines)

    # ----- 승인 -----
    def push_approvals(self):
        """승인 대기 요청을 대표 DM(과 '승인' 토픽이 있으면 거기도)에 한 번씩 올린다."""
        done = []
        with self.approval_lock:
            con, econ = outbox.connect(self.paths), executor.connect(self.paths)
            try:
                for r in executor.pending_approvals(econ):
                    k = f"approval:{r['id']}"
                    if outbox.kv_get(con, k):
                        continue
                    try:
                        fresh = executor.seal_of(self.paths, json.loads(r["payload"]))
                    except Exception as e:  # noqa: BLE001
                        fresh = f"계산 실패 {e}"
                    if fresh != r["seal"]:
                        self.say(self.alerts(), f"⚠️ {executor.tag(r['id'])} 승인 글을 올리지 않았습니다. 신청한 뒤 실행할 내용이 "
                                                f"바뀌어 안전 확인이 맞지 않습니다. 새로 신청해야 합니다."
                                 + plain.work(f"{executor.rid(r['id'])} 봉인 불일치"))
                        outbox.kv_set(con, k, "봉인 불일치")
                        continue
                    text, value = executor.approval_text(self.paths, r)
                    places = ["dm"] + (["승인"] if "승인" in self.msgr.topics else [])
                    for dest in places:
                        chat, msg = self.msgr.send(dest, text, buttons=[(label, action) for label, action in BUTTONS])
                        outbox.remember_post(con, chat, msg, "approval", value=value, buttons=BUTTONS, ref=text[:3000])
                    outbox.kv_set(con, k, config.stamp(self.cfg))
                    done.append(r["id"])
            finally:
                con.close()
                econ.close()
        return done

    def approval_bundle(self, label):
        fresh = self.push_approvals()
        econ = executor.connect(self.paths)
        try:
            rows = executor.pending_approvals(econ)
        finally:
            econ.close()
        old = [r for r in rows if r["id"] not in fresh]
        if old:
            when = "" if label == "지금" else f"{label} "
            self.say("dm", "\n".join([f"**🔔 {when}다시 알림 · 아직 결정 안 하신 승인 {len(old)}건**",
                                      "버튼은 처음 올린 글에 그대로 있습니다."]
                                     + [f"• {executor.tag(r['id'])} {plain.cut(r['title'], 90)}" for r in old]))
        return len(rows)

    def decided_line(self, value, decision, note=""):
        head = f"{DECIDED[decision]} · {config.now(self.cfg):%m/%d %H:%M}"
        if decision == "거부됨":
            return head + "\n아무것도 실행하지 않고 여기서 멈춥니다."
        if decision == "수정 요청":
            return head + (f"\n“{plain.cut(note, 200)}”" if note else "") + "\nJarvis 가 다음 대화에서 고쳐 새로 올립니다(이 요청은 실행하지 않습니다)."
        n, _seal = executor.parse_button(value)
        try:
            econ = executor.connect(self.paths)
            try:
                r = executor.get(econ, n)
            finally:
                econ.close()
            t = executor.target_cfg(self.paths, r["target"])
            return head + f"\n{executor.window_label(t['window'])} 실행합니다. 끝나면 알려 드립니다."
        except Exception:  # noqa: BLE001
            return head

    def mark_everywhere(self, value, line):
        con = outbox.connect(self.paths)
        try:
            for p in outbox.posts_for(con, "approval", value):
                try:
                    self.msgr.edit(p["chat"], p["msg"], (p["ref"] or "") + "\n\n" + line, buttons=None)
                except Exception:  # noqa: BLE001
                    log.exception("승인 글 고치기 실패 %s", p["msg"])
                outbox.clear_buttons(con, p["chat"], p["msg"])
        finally:
            con.close()

    def decide(self, value, decision, note=""):
        econ = executor.connect(self.paths)
        try:
            err = executor.decide(self.paths, econ, value, decision, self.key, note)
        except executor.ExecError as e:
            err = str(e)
        finally:
            econ.close()
        return err

    def handle_button(self, ev):
        con = outbox.connect(self.paths)
        try:
            row = outbox.post_of(con, ev["chat"], ev["msg"])
        finally:
            con.close()
        buttons = json.loads(row["buttons"]) if row and row["buttons"] else []
        if not row or ev["index"] >= len(buttons):
            return self.msgr.answer(ev["id"], "지난 버튼입니다.")
        action = buttons[ev["index"]][1]
        self.msgr.answer(ev["id"], "받았습니다.")
        if action == "revise":
            how = getattr(self.msgr, "reply_how", "이 글에 답장으로")
            chat, msg = self.msgr.send((ev["chat"], None), f"{executor.tag(executor.parse_button(row['value'])[0])} 무엇을 고칠까요? "
                                       f"{how} 적어 주세요.", reply_to=ev["msg"], force_reply=True)
            con = outbox.connect(self.paths)
            try:
                outbox.remember_post(con, chat, msg, "revise", value=row["value"])
            finally:
                con.close()
            return None
        decision = {"approve": "승인됨", "reject": "거부됨"}[action]
        err = self.decide(row["value"], decision)
        if err:
            return self.say((ev["chat"], None), f"⚠️ {err}", reply_to=ev["msg"])
        return self.mark_everywhere(row["value"], self.decided_line(row["value"], decision))

    def finish_revise(self, row, note):
        err = self.decide(row["value"], "수정 요청", note)
        if err:
            return self.say((row["chat"], None), f"⚠️ {err}")
        con = outbox.connect(self.paths)
        try:
            outbox.remember_post(con, row["chat"], row["msg"], "revise-done", value=row["value"])
        finally:
            con.close()
        return self.mark_everywhere(row["value"], self.decided_line(row["value"], "수정 요청", note))

    # ----- 보낼 글 -----
    def flush_once(self):
        self.beat("flush")
        con = outbox.connect(self.paths)
        try:
            for o in outbox.due(con):
                try:
                    if o["file"]:
                        self.msgr.send_file(o["dest"], o["file"], caption=o["text"][:900])
                        if len(o["text"]) > 900:
                            self.msgr.send(o["dest"], o["text"])
                    else:
                        self.msgr.send(o["dest"], o["text"])
                    outbox.done(con, o["id"])
                except Exception as e:  # noqa: BLE001
                    log.warning("보낼 글 실패 %s: %s", o["id"], e)
                    outbox.failed(con, o["id"], e, permanent=getattr(e, "permanent", False))
        finally:
            con.close()
        try:
            self.push_approvals()
        except Exception:  # noqa: BLE001
            log.exception("승인 글 올리기 실패")

    # ----- 예약 -----
    def jobs(self):
        files = [("Jarvis", self.paths.schedule)]
        if self.paths.skills.is_dir():
            files += [(d.name, d / "schedule.yaml") for d in sorted(self.paths.skills.iterdir()) if d.is_dir()]
        for owner, f in files:
            if not f.is_file():
                continue
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                log.warning("%s 읽기 실패: %s", f, e)
                continue
            for j in doc.get("작업") or doc.get("jobs") or []:
                j = norm_job(j)
                if j["enabled"] and cronlib.valid(j["cron"]):
                    yield owner, f.parent, j

    def scheduler_tick(self, now=None):
        t = (now or config.now(self.cfg)).replace(second=0, microsecond=0)
        due = []
        with self.state_lock:
            st = self.load_state()
            prev = t - timedelta(minutes=1)
            if st.get("checked"):
                try:
                    from datetime import datetime
                    prev = datetime.fromisoformat(st["checked"])
                except ValueError:
                    pass
            m = max(prev + timedelta(minutes=1), t - timedelta(minutes=15))
            while m <= t:
                for owner, folder, j in self.jobs():
                    key = f"{owner}/{j['name']}"
                    if cronlib.cron_match(j["cron"], m) and st["jobs"].get(key) != m.isoformat():
                        st["jobs"][key] = m.isoformat()
                        due.append((owner, folder, j, m))
                m += timedelta(minutes=1)
            st["checked"] = t.isoformat()
            self.save_state(st)
        for item in due:
            threading.Thread(target=self.run_job, args=item, daemon=True).start()
        return due

    def run_job(self, owner, folder, j, t):
        name, dest = j["name"], j["to"]
        try:
            if j["kind"] == "approvals":
                self.approval_bundle(f"{t:%H:%M}")
                out = ""
            elif j["kind"] == "prompt":
                ctx = (f"예약 작업 '{name}'. 지금은 {t:%Y-%m-%d %H:%M}. 네 답은 그대로 메신저에 올라간다. 짧게, 결과부터. "
                       f"알릴 것이 없으면 답 전체를 '{plain.QUIET}' 한 줄로 쓴다.")
                out = self.runner(self.cfg, self.paths, str(j["run"]), str(uuid.uuid4()), False, ctx,
                                  timeout=j["timeout_min"] * 60)
            elif j["kind"] == "script":
                plat = config.plat()
                r = subprocess.run([plat.sh(), "-c", str(j["run"])], cwd=str(folder), env=agent_env(self.cfg),
                                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=j["timeout_min"] * 60, stdin=subprocess.DEVNULL, **plat.popen_kw())
                out = (r.stdout.strip() or r.stderr.strip())[-3500:]
                if r.returncode != 0:
                    raise RuntimeError(f"종료 코드 {r.returncode}: {out[-300:]}")
            else:
                raise ValueError(f"종류를 모름: {j['kind']}")
            if dest and out and not plain.quiet(out):
                self.say(dest, out)
            st = self.job_fail.pop(f"{owner}/{name}", None)
            if st and st["n"] >= 3:
                self.say(self.alerts(), f"✅ 예약 '{name}' 이(가) 다시 잘 돕니다({st['n']}회 실패 뒤).")
        except Exception as e:  # noqa: BLE001
            log.exception("예약 실패 %s/%s", owner, name)
            st = self.job_fail.setdefault(f"{owner}/{name}", {"n": 0, "at": 0.0})
            st["n"] += 1
            if time.time() - st["at"] >= FAIL_REPEAT:
                self.say(self.alerts(), f"⚠️ 예약 '{name}' 이(가) 실패했습니다(연속 {st['n']}회). 다음 정해진 시각에 저절로 다시 돕니다. "
                                        "같은 실패는 6시간에 한 번만 알립니다." + plain.work(f"{owner}/{name} · {str(e)[:300]}"))
                st["at"] = time.time()

    # ----- 받기 -----
    def dispatch(self, ev):
        kind = ev["kind"]
        if kind == "answer":
            self.msgr.answer(ev["id"], ev["text"])
        elif kind == "leave":
            try:
                self.msgr.leave(ev["chat"])
            finally:
                self.say(self.alerts(), f"봇이 허락하지 않은 대화방에 들어가 바로 나왔습니다: {ev.get('title')}")
        elif kind == "button":
            threading.Thread(target=self.handle_button, args=(ev,), daemon=True).start()
        elif kind == "message":
            threading.Thread(target=self.handle_message, args=(ev,), daemon=True).start()

    def poll_forever(self):
        """받기를 메신저에 맡긴다(텔레그램 긴 기다림 · Slack Socket Mode · Discord 게이트웨이)."""
        self.msgr.listen(self.dispatch, self.beat, Store(self.paths))


class Store:
    """메신저가 받기 위치 같은 작은 값을 두는 곳(장부 outbox.db 의 kv)."""

    def __init__(self, paths):
        self.con = outbox.connect(paths)

    def get(self, k, default=None):
        return outbox.kv_get(self.con, k, default)

    def set(self, k, v):
        outbox.kv_set(self.con, k, v)

def norm_job(j):
    g = lambda *ks, d=None: next((j[k] for k in ks if k in j and j[k] is not None), d)  # noqa: E731
    kind = str(g("종류", "kind", d="prompt"))
    kind = {"지시": "prompt", "스크립트": "script", "승인묶음": "approvals"}.get(kind, kind)
    to = str(g("보낼곳", "to", d="") or "").strip()
    to = "dm" if to.upper() in ("DM",) else to.lstrip("#")
    state = str(g("상태", "enabled", d="켬")).strip().lower()
    try:
        tm = int(float(g("시간제한", "timeout_min", d=20)))
    except (TypeError, ValueError):
        tm = 20
    return {"name": str(g("이름", "name", d="?")), "cron": str(g("언제", "cron", d="")), "kind": kind,
            "run": g("실행", "run", d=""), "to": to, "enabled": state in ("켬", "on", "true", "yes", "1"),
            "timeout_min": tm}


def loop(fn, every):
    while True:
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("%s 실패", getattr(fn, "__name__", fn))
        time.sleep(every)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = config.load()
    paths = config.Paths(cfg).ensure()
    try:
        if not messengers.owner(cfg):
            raise messengers.NotReady(f"대표 {messengers.spec(cfg)['owner_word']} 가 없습니다")
        msgr = messengers.connect(cfg)
    except messengers.NotReady as e:
        log.error("%s. 설치(스킬 jarvis:setup)를 마치세요.", e)
        time.sleep(60)
        return 2
    key = secrets.get(secrets.SEAL, cfg)
    if not key:
        log.error("서명 열쇠(seal-key)가 없습니다. 승인 버튼이 동작하지 않습니다. /jarvis:setup 을 다시 돌리세요.")
    d = Daemon(cfg, paths, msgr, key)
    d.beat("started")  # 지킴이가 '막 뜬 것' 을 알아보게(맥·윈도 같은 방법)
    threading.Thread(target=loop, args=(d.flush_once, 5), daemon=True).start()
    threading.Thread(target=loop, args=(d.scheduler_tick, 20), daemon=True).start()
    log.info("시작. %s 대표 %s · 에이전트 %s", msgr.display, msgr.owner, agents.DISPLAY.get(d.agent, d.agent))
    try:
        d.poll_forever()
    except Exception:  # noqa: BLE001
        log.exception("%s 받기 멈춤", msgr.display)
        d.say(d.alerts(), f"⚠️ {msgr.display} 연결이 끊겨 스스로 다시 켭니다(보통 몇 분 안). 방금 보내신 말이 있으면 다시 켜진 뒤 한 번 더 해 주세요.")
        time.sleep(30)
    os._exit(1)


if __name__ == "__main__":
    sys.exit(main())
