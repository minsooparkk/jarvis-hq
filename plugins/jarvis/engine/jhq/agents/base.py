"""에이전트 층의 공통 모양과 하위 프로그램을 띄워 한 줄씩 읽는 고리.

Agent 가 갖출 것
- name·display(대표에게 보이는 이름)·home_file(세션이 늘 읽는 홈의 진입 파일)
- find(plat) → 실행 파일 자리 또는 None · path(cfg, plat) → 설정에 적힌 자리(없으면 찾은 것)
- argv(cfg, plat) → 실행 파일을 부를 앞부분(윈도 npm 의 .cmd 는 그 뒤의 진짜 프로그램으로)
- run(cfg, paths, prompt, session, resume=False, context="", timeout=None, on_text=None, on_tool=None,
      on_tick=None, register=None, stall=STALL) → Reply
    session: 이어 갈 대화 id. resume=False 면 새 대화(Claude 는 이 id 로 만들고, Codex 는 스스로 정한 id 를 Reply.session 에 돌려줌).
    context: 이번 실행에만 더할 시스템 지시(메신저 말투 등). on_text: 도구 사이에 쓴 글, on_tool: 쓰려는 도구 이름.
- prepare_home(paths, cfg) → 만든 것 목록: 이 에이전트가 홈에서 읽을 파일·연결을 맞춘다(멱등).
- checks(cfg, paths, plat) → [(이름, 맞음, 고칠 방법)] · guard() → 문지기 보장 표 [(항목, 같음|약함|강함, 설명)]

표준 라이브러리만 쓴다(설치 스크립트가 맥·윈도 기본 파이썬으로 불러 쓴다).
"""

import os
import queue
import subprocess
import threading
import time

STALL = 180  # 이 안에 한 줄도 내지 않으면 '시작 못 함'
STRIP_ENV = ("JARVIS_SEAL_KEY", "JARVIS_TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN",
             "DISCORD_BOT_TOKEN", "DISCORD_TOKEN")


class StallError(RuntimeError):
    pass


class Reply(str):
    """에이전트의 마지막 답. 글 그대로 쓰고, 실제로 쓰인 대화 id 는 .session 에 둔다."""

    def __new__(cls, text, session=None):
        obj = super().__new__(cls, text)
        obj.session = session
        return obj


def agent_env(cfg, extra_path=()):
    """에이전트 세션·예약 스크립트의 환경. 메신저 토큰·서명 열쇠는 빼고, PATH 앞에 jarvis 명령 자리를 더한다."""
    from .. import config
    plat = config.plat()
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    env["JARVIS_HQ_AGENT"] = cfg.get("assistant_name") or "Jarvis"
    extra = plat.agent_path(config.engine_dir()) + [p for p in extra_path if p]
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH") or plat.default_path()])
    env.setdefault("PYTHONUTF8", "1")
    return env


def stream(cmd, cwd, env, on_line, stdin_text=None, timeout=1200, stall=STALL, on_tick=None, register=None,
           who="에이전트"):
    """프로그램을 띄워 표준출력 한 줄마다 on_line(줄). (끝 코드, 표준오류 끝부분, 멈췄는지)를 돌려준다.
    stall 초 동안 한 줄도 없으면 StallError, timeout 초를 넘기면 RuntimeError(둘 다 프로그램을 끝낸 뒤)."""
    from .. import config
    plat = config.plat()
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL, text=True,
                            encoding="utf-8", errors="replace", bufsize=1, **plat.popen_kw())
    if stdin_text is not None:
        def feed():
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except OSError:
                pass
        threading.Thread(target=feed, daemon=True).start()
    if register:
        register(proc)
    lines, err = queue.Queue(), []

    def read_out():
        for ln in proc.stdout:
            lines.put(ln)
        lines.put(None)

    def read_err():
        for ln in proc.stderr:
            err.append(ln)
            del err[:-50]

    threading.Thread(target=read_out, daemon=True).start()
    threading.Thread(target=read_err, daemon=True).start()
    t0, seen = time.monotonic(), 0
    while True:
        try:
            ln = lines.get(timeout=1)
        except queue.Empty:
            ln = ""
        el = time.monotonic() - t0
        if ln is None:
            break
        if not ln:
            if not seen and el > stall:
                plat.kill(proc)
                raise StallError(f"{who} 가 {stall // 60}분 동안 시작하지 못했습니다: {''.join(err)[-300:].strip()}")
            if el > timeout:
                plat.kill(proc)
                raise RuntimeError(f"{timeout // 60}분 안에 끝나지 않음")
            if on_tick:
                on_tick(el)
            continue
        seen += 1
        on_line(ln)
    proc.wait()
    stopped = getattr(proc, "jarvis_stopped", False) or proc.returncode in (-9, -15)
    return proc.returncode, "".join(err), stopped


class Agent:
    name = "base"
    display = "?"
    home_file = "CLAUDE.md"
    exe = "agent"

    def find(self, plat):
        return None

    def path(self, cfg, plat):
        return self.configured(cfg) or self.find(plat) or self.exe

    def configured(self, cfg):
        return None

    def argv(self, cfg, plat):
        return [self.path(cfg, plat)]

    def run(self, cfg, paths, prompt, session, resume=False, context="", timeout=None, on_text=None, on_tool=None,
            on_tick=None, register=None, stall=STALL):
        raise NotImplementedError

    def prepare_home(self, paths, cfg=None, plat=None):
        return []

    def checks(self, cfg, paths, plat):
        return []

    def guard(self, cfg=None):
        return []

    def doctor_hint(self):
        """사람 손이 필요할 때 알릴 '점검 여는 법'."""
        return "이 컴퓨터에서 `jarvis agent status` 와 설치 점검(스킬 jarvis:doctor)을 돌려 주세요"
