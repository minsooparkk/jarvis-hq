#!/usr/bin/env python3
"""Jarvis 설치·점검·제거(표준 라이브러리만, 맥 기본 python3·윈도 python 으로 돈다). 스킬 setup·doctor·uninstall 이 부른다.

  python3 install.py [--home ~/jarvis] [--owner-name 이름] [--owner-title 대표] [--assistant-name Jarvis] [--tone "…"]
                     [--timezone Asia/Seoul] [--messenger telegram|slack|discord] [--owner-id id] [--telegram-owner-id 숫자]
                     [--agent claude|codex] [--dry-run] [--no-venv --python 경로] [--json]
  python3 install.py --doctor [--json]
  python3 install.py --uninstall [--remove-home] [--forget-secrets] [--dry-run] [--json]

멱등: 다시 돌려도 안전하다. 사용자 홈에 이미 있는 파일은 덮어쓰지 않는다(엔진 코드만 새 판으로 바꾸고 옛 판은 사본으로 남김).
--dry-run: 서비스 등록(맥 launchd·윈도 작업 스케줄러)·금고 쓰기를 하지 않고 '할 일'만 알려 준다
(파일은 HOME 아래에 쓴다. 시험은 임시 HOME 에서).
엔진 자리: ~/.jarvis-hq (JARVIS_HQ_DIR 로 바꿈). 플러그인 캐시 자리는 판마다 바뀌어 데몬을 거기 두지 않는다.
OS 마다 다른 일(서비스·금고·바로가기·폴더 연결·휴지통)은 엔진의 jhq.platform 이 맡는다(이 스크립트는 OS 를 직접 보지 않음).
에이전트(Claude Code · Codex)마다 다른 일(실행 파일 찾기, 홈의 AGENTS.md·.agents/skills, Codex 플러그인 넣기, 점검)은 jhq.agents 가 맡는다.
--agent 를 주지 않으면 설정 그대로(처음 설치는 claude). Codex 로 설치할 때는 --agent codex.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 플러그인 뿌리
TEMPLATE = ROOT / "template"
ENGINE_SRC = ROOT / "engine"
HOOKS_SRC = ROOT / "hooks"
MARKET_ROOT = ROOT.parent.parent  # 저장소에서 돌 때 마켓플레이스 뿌리(.claude-plugin/marketplace.json 이 있는 곳)
MARKET_REMOTE = "minsooparkk/jarvis-hq"
sys.path.insert(0, str(ENGINE_SRC))
from jhq import messengers as jm  # noqa: E402  메신저 목록(표준 라이브러리만, 연결 코드는 불러오지 않음)
from jhq import platform as osplat  # noqa: E402  표준 라이브러리만 쓰는 OS 층
from jhq import agents as jagents  # noqa: E402  표준 라이브러리만 쓰는 에이전트 층

SERVICES = ("jarvisd", "executor", "watchdog")
MODULE = {"jarvisd": "jhq.daemon", "executor": "jhq.cli", "watchdog": "jhq.watchdog"}
ARGS = {"executor": ["exec", "daemon"]}
# 시험용: 서비스 관리자(launchctl·schtasks)를 한 번도 부르지 않는다(옛 이름 JARVIS_HQ_NO_LAUNCHCTL 도 됨)
NO_SERVICES = bool(os.environ.get("JARVIS_HQ_NO_SERVICES") or os.environ.get("JARVIS_HQ_NO_LAUNCHCTL"))
PLAT = []


def plat():
    """이 컴퓨터의 OS 층. 시험은 PLAT 에 가짜 실행기를 낀 것을 넣는다."""
    if not PLAT:
        PLAT.append(osplat.current())
    return PLAT[0]
TEXT_EXT = (".md", ".yaml", ".yml", ".json", ".txt", ".py", ".sh")
SKIP = (".DS_Store", "__pycache__")


def home_dir():
    return Path(os.path.expanduser("~"))


def engine_dir():
    return Path(os.environ.get("JARVIS_HQ_DIR") or (home_dir() / ".jarvis-hq"))


def trash(path, report, dry=False):
    """지우는 대신 휴지통(사용자 폴더의 .Trash)으로."""
    return plat().trash(path, report, dry)


def tree_digest(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and not any(s in p.parts for s in SKIP) and p.suffix != ".pyc":
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def load_cfg():
    try:
        return json.loads((engine_dir() / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cfg(cfg):
    p = engine_dir() / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def plugin_version():
    try:
        return (ENGINE_SRC / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0"


# ---------- 설치 단계 ----------

def install_engine(report):
    """엔진 코드를 안정 자리(<엔진>/engine)에 깐다. 같으면 그대로, 다르면 옛 판을 backup 에 두고 바꾼다."""
    dest = engine_dir() / "engine"
    stage = engine_dir() / "engine.new"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(ENGINE_SRC, stage, ignore=shutil.ignore_patterns(*SKIP, "*.pyc"))
    (stage / "hooks").mkdir(exist_ok=True)
    for f in ("gate.py", "session_start.py"):
        shutil.copy2(HOOKS_SRC / f, stage / "hooks" / f)
    if (ROOT / ".mcp.json").exists():  # Codex 세션에 줄 MCP 서버(jhq.agents.codex)
        shutil.copy2(ROOT / ".mcp.json", stage / "mcp.json")
    if dest.exists() and tree_digest(dest) == tree_digest(stage):
        shutil.rmtree(stage)
        report["engine"] = "같음(그대로 둠)"
        return False
    if dest.exists():
        back = engine_dir() / "backup" / time.strftime("%Y%m%d-%H%M%S")
        back.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(back / "engine"))
        report["engine"] = f"새 판으로 바꿈(옛 판: {back / 'engine'})"
    else:
        report["engine"] = "깔았음"
    stage.rename(dest)
    return True


def ensure_python(args, report, cfg=None):
    p = plat()
    pkgs, mods = p.extra_requirements()
    sp = jm.spec(cfg or {})  # 고른 메신저의 패키지만(텔레그램은 없음)
    pkgs, mods = pkgs + sp["packages"], mods + sp["modules"]
    if args.no_venv:
        py = Path(args.python or sys.executable)
        report["python"] = str(py)
        return py
    venv = engine_dir() / "venv"
    py = p.venv_python(venv)
    base = args.python or sys.executable
    if not py.exists():
        subprocess.run([base, "-m", "venv", str(venv)], check=True)
        report["venv"] = "만듦"
    else:
        report["venv"] = "있음"
    probe = "import yaml" + "".join(f", {m}" for m in mods)
    ok = subprocess.run([str(py), "-c", probe], capture_output=True).returncode == 0
    if not ok:
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r",
                        str(engine_dir() / "engine" / "requirements.txt"), *pkgs], check=True)
        report["venv"] += " · 의존성 설치"
    report["python"] = str(py)
    return py


def install_cli(py, report):
    return plat().install_cli(engine_dir(), py, report)


def update_config(args, report):
    cfg = load_cfg()
    before = json.dumps(cfg, sort_keys=True)
    created = not cfg
    p = plat()
    defaults = {"home": str(Path(os.path.expanduser(args.home))), "label_prefix": args.label_prefix,
                "keychain_account": "jarvis-hq", "keychain_prefix": "jarvis-hq.",
                "assistant_name": args.assistant_name or "Jarvis", "owner_title": args.owner_title or "대표",
                "claude": p.find_claude() or str(p.user_bin() / "claude"),
                "agent_timeout_min": 20, "executor_tick_sec": 30,
                "telegram": {"owner_id": None, "group_id": None, "topics": {}}}
    for k, v in defaults.items():
        cfg.setdefault(k, v)
    cfg.setdefault("telegram", {}).setdefault("topics", {})
    if args.home_given:
        cfg["home"] = defaults["home"]
    if not Path(str(cfg.get("claude") or "")).exists() and p.find_claude():
        cfg["claude"] = p.find_claude()  # Claude Code 자리가 바뀌었으면 따라간다
    set_timezone(cfg, args, report, p)
    for k in ("assistant_name", "owner_title"):
        if getattr(args, k):
            cfg[k] = getattr(args, k)
    if args.messenger:
        cfg["messenger"] = args.messenger
    elif created:
        cfg["messenger"] = "telegram"
    if args.agent:
        cfg["agent"] = args.agent
    elif created or not cfg.get("agent"):
        cfg["agent"] = "claude"  # 예전 설치(agent 없음)는 Claude Code 그대로
    if cfg["agent"] == "codex":
        cx = cfg["codex"] if isinstance(cfg.get("codex"), dict) else {}
        cfg["codex"] = cx
        if not (cx.get("path") and Path(str(cx["path"])).exists()):
            found = jagents.get("codex").find(p)
            if found:
                cx["path"] = found  # Codex 자리가 바뀌었으면 따라간다
        if not cx.get("path"):
            report.setdefault("warnings", []).append(
                "codex 명령을 찾지 못했습니다. Codex CLI 를 깐 뒤(npm install -g @openai/codex) 설치를 다시 돌리세요.")
    for name in jm.NAMES:
        cfg.setdefault(name, {})
    if args.telegram_owner_id:
        cfg["telegram"]["owner_id"] = int(args.telegram_owner_id)
    if args.owner_id:
        jm.set_owner(cfg, args.owner_id)
    cfg["engine_version"] = plugin_version()
    save_cfg(cfg)
    report["config"] = ("만듦 " if created else "갱신 ") + str(engine_dir() / "config.json")
    report["config_changed"] = before != json.dumps(cfg, sort_keys=True)
    return cfg


def set_timezone(cfg, args, report, p):
    """--timezone 이 있으면 그것, 처음 설치면 이 컴퓨터의 시간대를 읽는다. 못 읽으면 기본(Asia/Seoul)을 두고 묻게 알린다.
    이미 있는 설정은 바꾸지 않는다(설치한 사람의 설정 그대로)."""
    from jhq import config as jconfig
    if args.timezone:
        if not jconfig.valid_timezone(args.timezone):
            raise RuntimeError(f"시간대 이름이 맞지 않습니다: {args.timezone} (예: Asia/Seoul, America/New_York)")
        cfg["timezone"] = args.timezone
        report["timezone"] = f"{args.timezone} (지정)"
        return
    if cfg.get("timezone"):
        report["timezone"] = cfg["timezone"]
        return
    found = p.default_timezone()
    if found and jconfig.valid_timezone(found):
        cfg["timezone"] = found
        report["timezone"] = f"{found} (이 컴퓨터 설정에서 읽음)"
    else:
        cfg["timezone"] = "Asia/Seoul"
        report["timezone"] = "Asia/Seoul (이 컴퓨터 시간대를 읽지 못해 기본값)"
        report["timezone_unknown"] = True


def render(text, values):
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def lay_home(cfg, args, report):
    home = Path(os.path.expanduser(cfg["home"]))
    values = {"OWNER_NAME": args.owner_name or "(이름을 적어 주세요)", "OWNER_TITLE": cfg.get("owner_title") or "대표",
              "ASSISTANT_NAME": cfg.get("assistant_name") or "Jarvis", "TONE": args.tone or "존댓말, 짧게, 결과부터",
              "HOME": str(home), "LABEL_PREFIX": cfg["label_prefix"]}
    created, kept = [], []
    for src in sorted(TEMPLATE.rglob("*")):
        if src.is_dir() or any(s in src.parts for s in SKIP):
            continue
        rel = src.relative_to(TEMPLATE)
        dest = home / rel
        if dest.exists():
            kept.append(str(rel))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEXT_EXT:
            dest.write_text(render(src.read_text(encoding="utf-8"), values), encoding="utf-8")
        else:
            shutil.copy2(src, dest)
        created.append(str(rel))
    for d in ("log", "decisions", "memory", "ledger", "state/logs", "work", "inbox"):
        (home / ".harness" / d).mkdir(parents=True, exist_ok=True)
    made = plat().link_dir(home / ".claude" / "skills", "../skills")  # 맥 심볼릭 링크, 윈도 디렉터리 정션
    if made:
        created.append(made)
    if cfg.get("agent") == "codex":  # AGENTS.md(CLAUDE.md 에서 만듦)와 .agents/skills(→ ../skills)
        from jhq import config as jconfig
        created += jagents.get("codex").prepare_home(jconfig.Paths(cfg), cfg, plat=plat())
    report["home"] = str(home)
    report["created"], report["kept"] = created, kept
    return home


def py_cli(py):
    """엔진 파이썬으로 jarvis 명령을 직접 부르는 앞부분(바로가기 파일·셸을 거치지 않음)."""
    return [str(py), "-m", "jhq.cli"]


def doctor_cli():
    e = engine_dir()
    py = plat().venv_python(e / "venv")
    if py.exists():
        return py_cli(py)
    cli = plat().cli_path(e)
    return [str(cli)] if cli.exists() else None


def run_cli(cli, *args, check=False):
    """cli: py_cli() 가 준 목록. 엔진 자리와 PYTHONPATH 를 맞춰 부른다."""
    e = engine_dir()
    env = {**os.environ, "JARVIS_HQ_DIR": str(e), "PYTHONUTF8": "1",
           "PYTHONPATH": str(e / "engine") + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")}
    r = subprocess.run([*cli, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"jarvis {' '.join(args)}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def codex_plugin(cfg, args, report):
    """Codex 에 플러그인 jarvis(스킬·MCP·훅)가 있는지 보고, 없으면 넣는다(같은 저장소의 .claude-plugin/marketplace.json 을
    Codex 가 읽는다). dry-run·서비스 끔(시험)에서는 할 일만 알린다. 사용자 Codex 설정(~/.codex/config.toml)에 마켓플레이스·
    플러그인 두 줄이 생긴다(그 밖의 Codex 설정은 건드리지 않음)."""
    ag = jagents.get("codex")
    p = plat()
    if not ag.configured(cfg):
        report["codex_plugin"] = "확인 못 함(codex 명령 없음)"
        return
    state = ag.plugin_state(cfg, p)
    if state == "installed":
        report["codex_plugin"] = "있음"
        return
    source = MARKET_ROOT if (MARKET_ROOT / ".claude-plugin" / "marketplace.json").exists() else MARKET_REMOTE
    plan = ag.plugin_plan(source)
    words = " && ".join("codex " + " ".join(str(x) for x in a) for a in plan)
    if args.dry_run or NO_SERVICES or state == "unknown":
        report["codex_plugin"] = f"할 일: {words}"
        return
    for a in plan:
        r = ag.cmd(cfg, p, *a, timeout=180)
        if r.returncode != 0 and "already" not in (r.stderr or r.stdout or "").lower():
            report.setdefault("warnings", []).append(f"codex {' '.join(str(x) for x in a)}: {(r.stderr or r.stdout or '').strip()[:200]}")
            report["codex_plugin"] = f"넣지 못함. 터미널에서: {words}"
            return
    report["codex_plugin"] = "넣었음(Codex 를 새로 열면 스킬 jarvis:… 가 보인다)"


def service_spec(cfg, svc, py, home):
    e = engine_dir()
    p = plat()
    env = {"JARVIS_HQ_DIR": str(e), "PYTHONPATH": str(e / "engine"), "LANG": "ko_KR.UTF-8"}
    path = p.service_path(e)
    if path:
        env["PATH"] = path
    return osplat.ServiceSpec(svc, f"{cfg['label_prefix']}.{svc}", py, MODULE[svc], ARGS.get(svc, []), workdir=home, env=env,
                              log=home / ".harness" / "state" / "logs" / f"{svc}.log", keepalive=svc != "watchdog",
                              interval=300 if svc == "watchdog" else None, engine=e)


def services(cfg, py, home, args, report, engine_changed, ready):
    """서비스 셋(jarvisd·실행기·지킴이)의 정의 파일을 쓰고, 준비됐으면 등록·다시 켜기(맥 launchd · 윈도 작업 스케줄러)."""
    p = plat()
    spy = py if args.no_venv else p.service_python(engine_dir() / "venv")
    actions = []
    for svc in SERVICES:
        spec = service_spec(cfg, svc, spy, home)
        changed = False
        for path, data in p.service_files(spec):
            if not path.exists() or path.read_bytes() != data:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                changed = True
        if not ready:
            continue
        loaded = not (args.dry_run or NO_SERVICES) and p.service_loaded(spec.label)
        actions += p.service_plan(spec, changed, loaded, engine_changed)
    report["services"] = [" ".join(str(x) for x in a) for a in actions] or (
        ["(바뀐 것 없음)"] if ready else ["(메신저 토큰·대표 id 를 마친 뒤 띄움)"])
    report["services_manager"] = p.service_word
    if args.dry_run or NO_SERVICES:
        report["services_dry_run"] = True
        return
    for w in p.apply(actions):
        report.setdefault("warnings", []).append(w)


def install(args):
    report = {"version": plugin_version(), "dry_run": bool(args.dry_run)}
    p = plat()
    if not p.supported:
        report["error"] = "아직 macOS·Windows 만 지원합니다. 이 운영체제에는 깔지 않았습니다."
        return report, 1
    try:
        report["shell"] = p.bash()  # 실행 대상·예약 스크립트를 돌릴 bash(윈도는 Git Bash 가 있어야 함)
    except osplat.Unsupported as e:
        report["error"] = str(e)
        return report, 1
    engine_changed = install_engine(report)
    cfg = update_config(args, report)
    py = ensure_python(args, report, cfg)
    install_cli(py, report)
    cli = py_cli(py)
    home = lay_home(cfg, args, report)
    report["agent"] = cfg.get("agent") or "claude"
    if report["agent"] == "codex":
        codex_plugin(cfg, args, report)
    r = run_cli(cli, "perms", "build")
    report["perms"] = (r.stdout or r.stderr).strip()
    if args.dry_run:
        report["seal_key"] = f"할 일: {p.vault_word}에 서명 열쇠 만들기(dry-run 이라 안 함)"
    else:
        run_cli(cli, "secret", "ensure-seal", check=True)
        report["seal_key"] = "있음"
    sec = run_cli(cli, "secret", "list").stdout
    m = jm.kind(cfg)
    sp = jm.SPECS[m]
    has_token = all(f"{n}: 있음" in sec for n in sp["secrets"])
    has_owner = bool(jm.owner(cfg))
    report["messenger"] = m
    report["messenger_token"], report["messenger_owner_id"] = has_token, has_owner
    if m == "telegram":  # 예전 이름(스킬·사용자 스크립트 호환)
        report["telegram_token"], report["telegram_owner_id"] = has_token, has_owner
    services(cfg, py, home, args, report, engine_changed or report.get("config_changed"), ready=has_token and has_owner)
    nxt = []
    if report.get("timezone_unknown"):
        nxt.append("이 컴퓨터의 시간대를 읽지 못했습니다. 사는 곳의 시간대(예: Asia/Seoul)를 물어 --timezone 으로 다시 돌림")
    cli_file = plat().cli_path(engine_dir())
    if not has_token:
        how = {"telegram": "BotFather 가 준 토큰", "slack": "Slack 앱의 봇 토큰(xoxb-)과 앱 토큰(xapp-)",
               "discord": "개발자 포털 Bot 화면의 토큰"}[m]
        cmds = " · ".join(f"{cli_file} secret set {x}" for x in {"telegram": ["telegram"], "slack": ["slack-bot", "slack-app"],
                                                                 "discord": ["discord"]}[m])
        nxt.append(f"대표가 자기 터미널에서: {cmds}  ({how}을 붙여 넣음. 채팅에 붙여 넣지 않음)")
    if has_token and not has_owner:
        nxt.append(f"봇에게 {sp['display']} 로 말을 건 뒤: jarvis messenger pair → 이름 확인 → jarvis messenger set-owner <id> → 설치 다시")
    if has_token and has_owner:
        nxt.append(f"{sp['display']} 에서 봇에게 '안녕' 을 보내고: jarvis status --wait-reply 180")
    if report["agent"] == "codex":
        nxt.append("Codex 로 돕니다. 문지기 보장(Claude 대비)과 점검: jarvis agent status")
    report["next"] = nxt
    return report, 0


# ---------- 점검 ----------

def doctor(args):
    cfg = load_cfg()
    p = plat()
    checks = []

    def add(name, ok, hint=""):
        checks.append({"name": name, "ok": bool(ok), "hint": "" if ok else hint})

    add("엔진 설정(config.json)", cfg, "/jarvis:setup 을 돌리세요")
    home = Path(os.path.expanduser(cfg.get("home") or "~/jarvis"))
    for f in ("CLAUDE.md", "RULES.md", "rules", "skills", "hooks", ".harness"):
        add(f"홈 {f}", (home / f).exists(), "/jarvis:setup 을 다시 돌리면 빠진 것만 채웁니다(있는 파일은 그대로)")
    e = engine_dir()
    add("엔진 코드", (e / "engine" / "jhq" / "daemon.py").exists(), "/jarvis:setup 을 다시 돌리세요")
    vf = e / "engine" / "VERSION"
    inst = vf.read_text(encoding="utf-8").strip() if vf.exists() else "없음"
    add(f"엔진 판(설치 {inst} · 플러그인 {plugin_version()})", inst == plugin_version(), "/jarvis:setup 을 다시 돌려 엔진을 새 판으로")
    py = p.venv_python(e / "venv")
    _pkgs, mods = p.extra_requirements()
    probe = "import yaml" + "".join(f", {m}" for m in mods)
    add("파이썬 환경(venv·PyYAML)", py.exists() and subprocess.run([str(py), "-c", probe], capture_output=True).returncode == 0,
        "/jarvis:setup 을 다시 돌리세요(인터넷 필요)")
    add("jarvis 명령", p.cli_path(e).exists(), "/jarvis:setup 을 다시 돌리세요")
    try:
        ag = jagents.get(cfg)
        from jhq import config as jconfig
        add(f"에이전트({ag.display})", True)
        for name, ok, hint in ag.checks(cfg, jconfig.Paths(jconfig._merge(jconfig.DEFAULTS, cfg)), p):
            add(name, ok, hint)
    except jagents.UnknownAgent as x:
        add("에이전트 이름", False, f"{x}. config.json 의 agent 는 claude · codex 중 하나")
    try:
        add(f"bash({p.bash()})", True)
    except osplat.Unsupported as x:
        add("bash", False, str(x))
    cli = doctor_cli()
    if cli:
        sec = run_cli(cli, "secret", "list").stdout
        sp = jm.spec(cfg) if cfg.get("messenger", "telegram") in jm.SPECS else jm.SPECS["telegram"]
        for n in sp["secrets"]:
            add(f"{sp['display']} 토큰 {n}({p.vault_word})", f"{n}: 있음" in sec, f"대표 터미널에서: {sp['secret_hint']}")
        add(f"승인 서명 열쇠({p.vault_word})", "seal-key: 있음" in sec, "/jarvis:setup 을 다시 돌리세요")
        pc = run_cli(cli, "perms", "check")
        add("권한 설정(settings.json)", pc.returncode == 0, (pc.stderr or pc.stdout).strip() + " → jarvis perms build")
    m = cfg.get("messenger") or "telegram"
    if m not in jm.SPECS:
        add(f"메신저 이름({m})", False, "config.json 의 messenger 는 telegram · slack · discord 중 하나")
    else:
        add(f"대표 {jm.SPECS[m]['owner_word']}", jm.owner(cfg, m), "jarvis messenger pair → set-owner")
    prefix = cfg.get("label_prefix") or "com.jarvis-hq"
    skip = args.dry_run or NO_SERVICES
    labels = [f"{prefix}.{svc}" for svc in SERVICES]
    states = {} if skip else p.service_states(labels)
    for svc, label in zip(SERVICES, labels):
        spec = service_spec(cfg, svc, p.service_python(e / "venv"), home)
        add(f"{p.service_word} {svc} 설정 파일", all(path.exists() for path, _ in p.service_files(spec)), "/jarvis:setup")
        if not skip:
            add(f"{p.service_word} {svc} 등록", (states.get(label) or ("missing",))[0] != "missing",
                "/jarvis:setup 을 다시 돌리세요(토큰·대표 id 가 있어야 띄움)")
    hb = home / ".harness" / "state" / "jarvisd.heartbeat"
    try:
        age = time.time() - float(json.loads(hb.read_text(encoding="utf-8")).get("flush"))
    except (OSError, ValueError, TypeError):
        age = None
    add("jarvisd 심장박동(5분 안)", age is not None and age < 300, "로그: " + str(home / ".harness" / "state" / "logs" / "jarvisd.log"))
    add("실행기 멈춤 표시 없음", not (home / ".harness" / "state" / "executor.pause").exists(),
        "대표가 일부러 멈춘 것이면 그대로. 풀기: 대표 터미널에서 jarvis exec resume")
    bad = [c for c in checks if not c["ok"]]
    return {"ok": not bad, "checks": checks}, (0 if not bad else 1)


# ---------- 제거 ----------

def uninstall(args):
    report = {"dry_run": bool(args.dry_run)}
    cfg = load_cfg()
    p = plat()
    if not p.supported:
        return {"error": "아직 macOS·Windows 만 지원합니다."}, 1
    prefix = cfg.get("label_prefix") or "com.jarvis-hq"
    e = engine_dir()
    for svc in SERVICES:
        label = f"{prefix}.{svc}"
        acts = p.service_remove_plan(label)
        report.setdefault("services", []).extend(" ".join(a) for a in acts)
        if not (args.dry_run or NO_SERVICES):
            p.apply(acts)
        for f in p.service_files_of(label, e):
            trash(f, report, args.dry_run)
    p.remove_cli(e, report, args.dry_run)
    if args.forget_secrets:
        acct = cfg.get("keychain_account") or "jarvis-hq"
        prefix_kc = cfg.get("keychain_prefix") or "jarvis-hq."
        names = ["telegram-bot-token", "seal-key"] + [n for sp in jm.SPECS.values() for n in sp["secrets"]
                                                       if n != "telegram-bot-token"] + list(cfg.get("secret_names") or [])
        for n in names:
            if not args.dry_run and not os.environ.get("JARVIS_HQ_FAKE_KEYCHAIN"):
                try:
                    p.secret_delete(prefix_kc + n, acct)
                except (OSError, RuntimeError) as x:
                    report.setdefault("warnings", []).append(f"{n} 지우기 실패: {x}")
            report.setdefault("secrets_deleted", []).append(n)
    home = Path(os.path.expanduser(cfg.get("home") or "~/jarvis"))
    if args.remove_home:
        trash(home, report, args.dry_run)
    else:
        report["home_kept"] = str(home)
    trash(e, report, args.dry_run)
    if cfg.get("agent") == "codex":
        report["codex_plugin"] = "Codex 플러그인은 그대로 둡니다. 빼려면: codex plugin remove jarvis@jarvis-hq"
    return report, 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Jarvis 설치·점검·제거")
    ap.add_argument("--home", default=None)
    ap.add_argument("--owner-name", default="")
    ap.add_argument("--owner-title", default="")
    ap.add_argument("--assistant-name", default="")
    ap.add_argument("--tone", default="")
    ap.add_argument("--timezone", default="", help="IANA 시간대 이름(예: Asia/Seoul). 없으면 처음 설치 때 이 컴퓨터에서 읽음")
    ap.add_argument("--telegram-owner-id", default="")
    ap.add_argument("--messenger", default="", choices=["", *jm.NAMES], help="telegram(기본) · slack · discord")
    ap.add_argument("--owner-id", default="", help="고른 메신저의 대표 id")
    ap.add_argument("--agent", default="", choices=["", *jagents.NAMES], help="claude(기본) · codex. 없으면 설정 그대로")
    ap.add_argument("--label-prefix", default="com.jarvis-hq")
    ap.add_argument("--python", default="")
    ap.add_argument("--no-venv", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--doctor", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--remove-home", action="store_true")
    ap.add_argument("--forget-secrets", action="store_true")
    a = ap.parse_args(argv)
    a.home_given = a.home is not None
    a.home = a.home or "~/jarvis"
    try:
        if a.doctor:
            report, code = doctor(a)
        elif a.uninstall:
            report, code = uninstall(a)
        else:
            report, code = install(a)
    except (subprocess.CalledProcessError, RuntimeError, OSError, ValueError, osplat.Unsupported) as e:
        report, code = {"error": str(e)[:500]}, 1
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for k, v in report.items():
            if isinstance(v, list):
                print(f"{k}:")
                for x in v:
                    print(f"  - {x if not isinstance(x, dict) else ('OK ' if x['ok'] else '!! ') + x['name'] + (' → ' + x['hint'] if x['hint'] else '')}")
            else:
                print(f"{k}: {v}")
    return code


if __name__ == "__main__":
    sys.exit(main())
