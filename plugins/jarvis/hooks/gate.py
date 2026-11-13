#!/usr/bin/env python3
"""Jarvis 문지기(PreToolUse 훅). 표준 라이브러리만 쓴다(맥 기본 python3·윈도 python 으로 돈다).

권한 규칙(settings.json)은 명령 첫머리만 보므로, 인자까지 봐야 하는 '되돌릴 수 없는 일'과 비밀값만 여기서 막는다.
막을 때만 한 줄 JSON(permissionDecision=deny, 이유에 대신할 길)을 내고, 그 밖에는 아무 말도 하지 않는다.
보안 경계가 아니라 실수 방지 울타리다(같은 맥 사용자 권한으로 도는 Agent 를 완전히 가둘 수는 없다). docs/보안-모델.md

어디에 걸리나
- 언제나(모든 세션): Jarvis 자신의 울타리. 비밀값 넣기·지우기, 실행기 전용 입구(데몬·서명·보내기 몸통),
  Jarvis 키체인 항목 읽기, <홈>/hooks/(문지기·실행 대상·권한 설정)와 <홈>/.harness/ledger/(장부) 쓰기.
- Jarvis 세션 안(작업 폴더가 Jarvis 홈 아래이거나 jarvisd 가 띄운 세션, 또는 gate.json scope=all):
  rm 은 임시·작업 폴더·휴지통 아래만, git push 는 허락한 원격만(강제·지우기 금지), 보호 DB 는 읽기 전용,
  launchd 서비스 내리기·kill -9 금지, 배포·공개 명령은 실행기로, docker prune 금지, 키체인·비밀 파일 읽기 금지,
  밖으로 보내는 MCP 도구(메일·메시지 보내기, 영구 삭제) 금지, '길 고정'(routes) 규칙, 하위 Agent 의 바깥 입구 금지.
설정: <홈>/hooks/gate.json (없으면 기본값). 엔진 설정: ~/.jarvis-hq/config.json (JARVIS_HQ_DIR 로 바꿀 수 있음).
Codex(OpenAI Codex CLI)에서도 같은 파일이 돈다(입력·출력 모양이 같음). Codex 만의 도구: apply_patch(패치 글의 파일 자리를 봄),
write_stdin(이미 띄운 프로그램에 넣는 글을 셸 명령처럼 봄). Bash 명령이 목록(["bash", "-lc", "…"])으로 와도 읽는다.
윈도: 이 훅은 엔진(jhq.platform)을 부를 수 없는 혼자 도는 스크립트라 OS 를 여기서 한 번(WIN) 본다. 경로는 / 와 소문자로 맞춰
비교하고, Git Bash 꼴(/c/Users/…)도 읽는다. schtasks·taskkill·cmdkey, PowerShell 도구의 명령도 본다.
"""

import json
import os
import re
import shlex
import sys
import tempfile
import unicodedata

WIN = os.name == "nt"
HOME = os.path.expanduser("~")


def nfc(s):
    return unicodedata.normalize("NFC", s)


def norm(p):
    """비교용 경로. 윈도는 대소문자를 가리지 않고 \\ 와 / 를 섞어 쓰므로 / 와 소문자로 맞춘다."""
    p = nfc(p)
    return p.replace("\\", "/").lower() if WIN else p


TMP_OK = ((norm(tempfile.gettempdir()).rstrip("/") + "/",) if WIN
          else ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/"))
DEPLOY = (  # (명령, 뒤 낱말들에 맞으면 막는 패턴) — 배포·공개·되돌릴 수 없는 바깥 변경
    ("wrangler", r"\b(deploy|publish)\b"), ("vercel", r"^$|^(deploy\b|--prod)|\s--prod\b"), ("netlify", r"\bdeploy\b"),
    ("firebase", r"\bdeploy\b"), ("flyctl", r"^deploy\b"), ("fly", r"^deploy\b"), ("npm", r"^(publish|unpublish)\b"),
    ("pnpm", r"^publish\b"), ("yarn", r"^(npm )?publish\b"), ("twine", r"^upload\b"), ("docker", r"^push\b"),
    ("gh", r"^(release (create|delete|upload|edit)|pr merge|repo (create|delete|edit|rename)|api .*(-X|--method) ?(POST|DELETE|PATCH|PUT))"),
    ("terraform", r"^(apply|destroy)\b"), ("kubectl", r"^(apply|delete|replace)\b"),
)
MCP_SEND = re.compile(r"(^|_)(send|reply|forward|delete|trash|publish|post|schedule_message|set_vacation|respond_to_event|"
                      r"share|invite|upload)(_|$)")  # 도구 이름의 마지막 토막(…__<이것>)에서 찾는다
SECRET_FILE = re.compile(r"(^|/)(\.env(\..*)?|\.dev\.vars|[^/]*\.pem|[^/]*\.p12|id_(rsa|ed25519|ecdsa)[^/]*|"
                         r"[^/]*\.token|credentials(\.json)?|\.netrc|\.npmrc|\.pypirc)$")
SECRET_DIRS = tuple(norm(os.path.join(HOME, d)).rstrip("/") + "/" for d in (
    ".ssh", "Library/Keychains", ".config/gh", ".aws", ".gnupg",
    "AppData/Roaming/Microsoft/Credentials", "AppData/Local/Microsoft/Credentials", "AppData/Roaming/Microsoft/Protect"))
READERS = ("cat", "head", "tail", "less", "more", "bat", "grep", "rg", "awk", "sed", "strings", "xxd", "od", "base64",
           "cp", "scp", "rsync", "open", "nl", "sort", "uniq", "diff", "tar", "zip")
WRITERS = ("rm", "rmdir", "unlink", "touch", "mkdir", "truncate", "chmod", "chown", "shred", "mv", "ln")
INTERPRETER = re.compile(r"^(python[0-9.w]*|py|node|perl|ruby|bash|sh|zsh|deno|bun|osascript|powershell|pwsh)$")
VAULT_READ = re.compile(r"keyring|credread|find-generic-password|get-storedcredential|cmdkey", re.I)
PS_DELETE = re.compile(r"(?i)(^|[\s;|&(])(remove-item|rm|del|erase|rd|rmdir|clear-recyclebin)(\s|$)")
PS_WRITE = re.compile(r"(?i)\b(set-content|add-content|out-file|new-item|copy-item|move-item|remove-item|rename-item|"
                      r"clear-content|tee-object)\b|>")
PS_STOP = re.compile(r"(?i)\b(stop-process|unregister-scheduledtask|stop-scheduledtask|disable-scheduledtask|stop-service)\b")
CODE_WRITE = re.compile(r"open\([^)]*['\"][wax]\+?b?['\"]|write_text|write_bytes|\.write\(|json\.dump\(|os\.(remove|unlink|"
                        r"rename|replace)|shutil\.|\.unlink\(|\.rename\(|writeFile|appendFile|sqlite3\.connect")
DEFAULTS = {
    "scope": "home",
    "rm_ok": [],
    "push_ok": [],
    "protected_services": [],
    "protected_procs": [],
    "protected_dbs": [],
    "extra_deploy": [],
    "mcp_block": [],
    "mcp_allow": [],
    "routes": [
        {"match": ["whisper-cli", "faster-whisper", "whisperx", "mlx_whisper", "import whisper"],
         "allow": ["jarvis", "grep", "rg", "ls", "which", "brew", "pytest"],
         "message": "녹음 받아쓰기는 `jarvis stt <파일>` 로만 합니다(스킬 transcribe)."},
    ],
}


def load():
    engine = os.environ.get("JARVIS_HQ_DIR") or os.path.join(HOME, ".jarvis-hq")
    try:
        with open(os.path.join(engine, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    home = os.path.realpath(os.path.expanduser(str(cfg.get("home") or "~/jarvis")))
    g = dict(DEFAULTS)
    try:
        with open(os.path.join(home, "hooks", "gate.json"), encoding="utf-8") as f:
            g.update({k: v for k, v in json.load(f).items() if not k.startswith("_")})
    except (OSError, ValueError):
        pass
    return {"engine": os.path.realpath(engine), "home": home, "prefix": str(cfg.get("label_prefix") or "com.jarvis-hq"),
            "kc": str(cfg.get("keychain_prefix") or "jarvis-hq."), "gate": g}


def cmdname(a):
    """명령 이름: 경로를 떼고, 윈도 꼴(.exe 등·대문자)은 맞춘다."""
    b = os.path.basename(str(a).replace("\\", "/"))
    low = b.lower()
    for ext in (".exe", ".cmd", ".bat"):
        if low.endswith(ext):
            return low[:-len(ext)]
    return low if WIN else b


def from_msys(p):
    """Git Bash 꼴 경로(/c/Users/…, /tmp/…)를 윈도 경로로."""
    m = re.match(r"^/([a-zA-Z])(/|$)", p)
    if m:
        return m.group(1).upper() + ":/" + p[3:]
    if p == "/tmp" or p.startswith("/tmp/"):
        return tempfile.gettempdir() + p[4:]
    return p


def segments(command):
    """;·&&·||·| 로 나눈 (낱말들, 리다이렉트 대상들) 목록. 읽을 수 없으면 None."""
    try:
        lx = shlex.shlex(command, posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        toks = list(lx)
    except ValueError:
        return None
    out, cur, red, i = [], [], [], 0
    while i < len(toks):
        t = toks[i]
        if t and all(c in ";&|<>()" for c in t):
            if ">" in t and t not in (">&", "<&") and i + 1 < len(toks):
                red.append(toks[i + 1])
                i += 2
                continue
            if "<" in t and i + 1 < len(toks):
                i += 2
                continue
            if cur or red:
                out.append((cur, red))
            cur, red = [], []
        else:
            cur.append(t)
        i += 1
    if cur or red:
        out.append((cur, red))
    return out


def strip_prefix(argv):
    i = 0
    while i < len(argv):
        t = argv[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t) or t in ("sudo", "env", "nice", "nohup", "command", "exec", "time"):
            i += 1
            continue
        if t in ("timeout", "gtimeout"):
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or re.match(r"^[0-9.]+[smhd]?$", argv[i])):
                i += 1
            continue
        break
    return argv[i:]


def absp(p, cwd):
    p = os.path.expanduser(p)
    if WIN:
        p = from_msys(p)
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    return norm(os.path.realpath(p))


def under(path, root):
    root = norm(os.path.realpath(root))
    return path == root or path.startswith(root.rstrip("/") + "/")


def deny(reason):
    return "deny", reason


# ---------- 언제나 ----------

def protected_dirs(c):
    return [os.path.join(c["home"], "hooks"), os.path.join(c["home"], ".harness", "ledger"), c["engine"]]


PROTECT_MSG = ("<홈>/hooks/(문지기·실행 대상·권한 설정)·장부·엔진은 Jarvis 가 직접 고치지 않습니다. 설정을 바꿀 때는 새 내용을 "
               "만들어 `jarvis exec request --target config-apply --input 파일.json …` 으로 대표 승인을 받습니다(스킬 approval-request).")


def always_bash(argv, red, cwd, c, text):
    base = cmdname(argv[0]) if argv else ""
    sub = argv[1:3]
    if base == "jarvis":
        if sub[:2] in (["secret", "set"], ["secret", "delete"]):
            return deny("비밀값 넣기·지우기는 대표가 자기 터미널에서 직접 합니다(값을 채팅에 붙여 넣지 않음).")
        if sub[:2] in (["exec", "resume"], ["exec", "daemon"]) or sub[:1] == ["daemon"] or sub[:2] == ["mail", "send"]:
            return deny("실행기 다시 켜기·데몬·보내기 몸통은 대표와 실행기만 씁니다.")
        if sub[:2] == ["agent", "set"]:
            return deny("에이전트(Claude Code·Codex) 바꾸기는 문지기·권한 모양이 바뀌는 일이라 대표가 자기 터미널에서 합니다.")
    joined = " ".join(argv)
    if re.search(r"jhq\.(daemon|watchdog)|jhq\.extras\.gmail\s+send|jhq\.apply_config|jhq/(daemon|executor|apply_config)\.py", joined) \
            or ("jhq.executor" in joined and "daemon" in argv) or ("jhq.cli" in joined and ("daemon" in argv or "resume" in argv)):
        return deny("실행기·데몬 전용 입구는 직접 부르지 않습니다. 승인 요청(jarvis exec request)으로.")
    if base in ("security", "cmdkey") and c["kc"] in joined:
        return deny("Jarvis 금고 값은 읽지 않습니다. 프로그램이 필요하면 엔진이 스스로 읽습니다.")
    if (INTERPRETER.match(base) or base.endswith("python")) and c["kc"] in text and VAULT_READ.search(text):
        return deny("Jarvis 금고 값은 읽지 않습니다. 프로그램이 필요하면 엔진이 스스로 읽습니다.")
    if re.search(r"executor\.pause", joined) and base in ("rm", "mv", "unlink", "trash"):
        return deny("실행기 멈춤 표시는 대표만 풉니다(대표 터미널: jarvis exec resume).")
    prot = protected_dirs(c)
    targets = list(red)
    paths = [a for a in argv[1:] if not a.startswith("-")]
    if base == "tee":
        targets += paths
    if base in ("cp", "rsync", "install", "ditto", "mv", "ln") and paths:
        targets.append(paths[-1])
    if base in WRITERS:
        targets += paths
    if base in ("sed", "gsed", "perl") and any(a.startswith("--in-place") or (a.startswith("-") and not a.startswith("--")
                                                                             and "i" in a[1:]) for a in argv[1:]):
        targets += paths
    if base == "dd":
        targets += [a[3:] for a in argv[1:] if a.startswith("of=")]
    for t in targets:
        if t and not t.startswith("&") and any(under(absp(t, cwd), d) for d in prot):
            return deny(PROTECT_MSG)
    if (INTERPRETER.match(base) or base.endswith("python")) and CODE_WRITE.search(text):
        rel = under(absp(cwd or ".", cwd), c["home"]) and re.search(
            r"(^|[\s'\"/=(])(\.harness/ledger|hooks/(gate|targets|permissions)\.)", text)
        t = norm(text)
        if any(norm(d) in t or norm(d).replace(norm(HOME), "~") in t for d in prot) or rel:
            return deny(PROTECT_MSG)
    return None


# ---------- Jarvis 세션 안 ----------

def judge_rm(argv, cwd, c):
    ok = list(TMP_OK) + [os.path.join(HOME, ".Trash") + "/", os.path.join(c["home"], ".harness", "work") + "/"] + \
        [os.path.expanduser(x).rstrip("/") + "/" for x in c["gate"].get("rm_ok") or []]
    for p in [t for t in argv[1:] if not t.startswith("-")]:
        real = absp(p, cwd)
        if not any((real + "/").startswith(norm(os.path.realpath(o.rstrip("/\\"))).rstrip("/") + "/") for o in ok):
            return deny(f"지우는 대신 휴지통으로: mv {shlex.quote(p)} ~/.Trash/ (rm 은 임시 폴더·작업 폴더·휴지통 아래만)")
    return None


def remote_url(repo, remote):
    import subprocess
    try:
        r = subprocess.run(["git", "-C", repo, "remote", "get-url", "--push", remote], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def norm_url(u):
    u = re.sub(r"^(https?://|ssh://)([^@/]+@)?", "", u.strip())
    return re.sub(r"^git@([^:]+):", r"\1/", u).replace(".git", "")


def judge_git(argv, cwd, c, agent_id):
    repo, i = cwd or os.getcwd(), 1
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] == "-C" and i + 1 < len(argv):
            repo = absp(argv[i + 1], cwd)
            i += 2
        elif argv[i] == "-c" and i + 1 < len(argv):
            i += 2
        else:
            i += 1
    if i >= len(argv) or argv[i] != "push":
        return None
    rest = argv[i + 1:]
    for t in rest:
        if t in ("-f", "--force", "--mirror", "-d", "--delete", "--prune") or t.startswith("--force") \
                or (t.startswith("+") and len(t) > 1) or (t.startswith(":") and len(t) > 1):
            return deny(f"되돌릴 수 없는 push 는 하지 않습니다({t}). 필요하면 대표에게.")
    if agent_id:
        return deny("하위 Agent 는 push 하지 않습니다. 커밋까지 하고 돌려주면 Jarvis 가 검토 뒤 올립니다.")
    ok = c["gate"].get("push_ok") or []
    remote = next((t for t in rest if not t.startswith("-")), "origin")
    url = norm_url(remote_url(repo, remote))
    if not url:
        return deny(f"push 원격 {remote} 의 주소를 확인하지 못했습니다.")
    if not any(url.startswith(norm_url(o)) for o in ok):
        return deny(f"허락한 원격만 push 합니다({url} 은 목록에 없음). 대표의 비공개 저장소면 hooks/gate.json 의 push_ok 에 "
                    "더해 달라고 하고, 공개·공동 저장소면 실행기 승인으로.")
    return None


def judge_segment(argv, cwd, c, agent_id):
    g = c["gate"]
    base = cmdname(argv[0])
    words = [t for t in argv[1:] if not t.startswith("-")]
    if base == "rm":
        return judge_rm(argv, cwd, c)
    if base == "git":
        return judge_git(argv, cwd, c, agent_id)
    if base == "sqlite3":
        dbs = ("executor.db", "outbox.db") + tuple(g.get("protected_dbs") or [])
        hit = next((t for t in argv[1:] if any(d in t for d in dbs)), "")
        if hit and "-readonly" not in argv and "mode=ro" not in hit:
            return deny(f"장부·운영 DB 는 읽기만: sqlite3 -readonly {hit} … (쓰기는 그 프로그램이 합니다)")
    if base == "launchctl" and len(argv) > 1 and argv[1] in ("bootout", "unload", "kill", "kickstart", "stop", "remove",
                                                              "disable", "bootstrap", "load", "enable"):
        prot = (c["prefix"],) + tuple(g.get("protected_services") or [])
        hit = next((t for t in argv[2:] if any(p in t for p in prot)), "")
        if hit:
            return deny(f"{hit} 는 대표·설치 스킬만 내리고 띄웁니다. 상태 보기는 launchctl print·list 로.")
    low = [a.lower() for a in argv[1:]]
    if base == "schtasks" and any(a in ("/delete", "/end", "/change", "/run", "/create") for a in low):
        prot = (c["prefix"],) + tuple(g.get("protected_services") or [])
        hit = next((t for t in argv[2:] if any(p in t for p in prot)), "")
        if hit:
            return deny(f"{hit} 는 대표·설치 스킬만 내리고 띄웁니다. 상태 보기는 schtasks /Query 로.")
    if base == "taskkill":
        if "/f" in low:
            return deny("강제 종료(/F)는 하지 않습니다. 필요하면 /F 없이 /PID 로.")
        if "/im" in low:
            return deny("이름으로 죽이기(/IM)는 같은 이름 프로세스를 다 죽여 쓰지 않습니다. /PID 로.")
    if base == "cmdkey" and any(a.startswith("/delete") or a.startswith("/add") or a.startswith("/generic") for a in low):
        return deny("자격 증명 관리자 항목은 바꾸거나 지우지 않습니다. 비밀값은 대표가 터미널에서 jarvis secret 으로.")
    if base in ("powershell", "pwsh"):
        r = judge_ps_text(" ".join(argv[1:]), cwd, c)
        if r:
            return r
    if base in ("kill", "pkill", "killall"):
        if base == "killall":
            return deny("killall 은 이름이 같은 프로세스를 다 죽여 쓰지 않습니다. pkill -TERM -f <정확한 이름> 으로.")
        if any(t in ("-9", "-KILL", "-SIGKILL") or t.startswith("-s") for t in argv[1:]):
            return deny("강제 종료(-9·KILL)는 하지 않습니다. 필요하면 -TERM 으로.")
        procs = ("jhq.daemon", "jhq.executor", "jhq.watchdog", "jhq.cli") + tuple(g.get("protected_procs") or [])
        hit = next((t for t in argv[1:] if any(p in t for p in procs)), "")
        if hit:
            return deny(f"{hit} 는 Jarvis·실행기·지킴이라 죽이지 않습니다(지킴이가 다시 띄웁니다).")
    rules = DEPLOY + tuple((str(d.get("cmd")), str(d.get("pattern"))) for d in g.get("extra_deploy") or [])
    call, rest = (argv[1:2] and cmdname(argv[1]), argv[2:]) if base in ("npx", "bunx") else (base, argv[1:])
    for tool, pat in rules:
        if call == tool and re.search(pat, " ".join(rest)):
            return deny(f"배포·공개처럼 되돌릴 수 없는 일은 실행기 승인으로만 합니다(`jarvis exec request --target …`). {tool} 조회 명령은 됩니다.")
    if base == "docker" and words[:2] in (["volume", "prune"], ["system", "prune"], ["volume", "rm"]):
        return deny("Docker 볼륨은 지우거나 정리하지 않습니다.")
    if base == "security" and len(argv) > 1 and argv[1] in ("find-generic-password", "find-internet-password", "dump-keychain",
                                                             "export", "delete-generic-password"):
        return deny("키체인 값은 읽지 않습니다. 비밀값 이름·있는지만 보려면 `jarvis secret list`.")
    if base in READERS:
        for p in [t for t in argv[1:] if not t.startswith("-")]:
            real = absp(p, cwd)
            if SECRET_FILE.search(real) or any(real.startswith(d) for d in SECRET_DIRS):
                return deny(f"비밀값 파일은 열지 않습니다({os.path.basename(real)}). 프로그램이 값을 쓰면 엔진이 금고에서 넣습니다.")
    if base in ("printenv", "env") and len(argv) == 1:
        return None
    if agent_id and base == "jarvis" and argv[1:2] in (["exec"], ["notify"], ["mail"]) and \
            (argv[2:3] in (["request"],) or argv[1:2] == ["notify"]):
        return deny("하위 Agent(Agent 도구로 맡긴 일)는 승인 요청·알림을 내지 않습니다. 결과를 돌려주면 Jarvis 가 검토 뒤 냅니다.")
    return None


def judge_routes(command, segs, c):
    low = command.lower()
    bases = [cmdname(strip_prefix(a)[0]) for a, _r in segs if strip_prefix(a)]
    for r in c["gate"].get("routes") or []:
        if any(str(m).lower() in low for m in r.get("match") or []):
            if bases and (bases[0] == "pytest" or "-m pytest" in command):
                continue
            if bases and all(b in (r.get("allow") or []) for b in bases):
                continue
            return deny(str(r.get("message") or "이 일은 정해진 명령으로만 합니다."))
    return None


def in_scope(cwd, c):
    if c["gate"].get("scope") == "all" or os.environ.get("JARVIS_HQ_AGENT"):
        return True
    return bool(cwd) and (under(absp(cwd, cwd), c["home"]) or under(absp(cwd, cwd), c["engine"]))


def judge_bash(command, cwd, c, agent_id=""):
    segs = segments(command)
    scope = in_scope(cwd, c)
    if segs is None:
        if re.search(r"\b(rm|git push|security|launchctl|kill|jarvis)\b", command):
            return deny("명령을 읽을 수 없어 확인하지 못했습니다(따옴표 확인). 한 줄에 하나씩.")
        return None
    here = cwd or os.getcwd()
    for argv, red in segs:
        argv = strip_prefix(argv)
        if not argv and not red:
            continue
        if argv and cmdname(argv[0]) == "cd":
            here = absp(argv[1] if len(argv) > 1 else HOME, here)
            continue
        r = always_bash(argv or [""], red, here, c, command)
        if r:
            return r
        if scope and argv:
            r = judge_segment(argv, here, c, agent_id)
            if r:
                return r
    if scope:
        return judge_routes(command, segs, c)
    return None


def judge_ps_text(command, cwd, c):
    """PowerShell 명령 글(윈도의 PowerShell 도구, 또는 bash 안의 powershell -Command …)에서 막을 것.
    PowerShell 문법은 다 읽지 못한다. 지우기·서비스 멈추기·금고 읽기·울타리 쓰기 꼴만 넓게 막는다."""
    if re.search(r"(?i)\bjarvis(\.cmd)?\s+(secret\s+(set|delete)|exec\s+(resume|daemon)|mail\s+send)\b", command):
        return deny("비밀값 넣기·지우기, 실행기 다시 켜기·데몬·보내기 몸통은 대표와 실행기만 씁니다.")
    t = norm(command)
    prot = protected_dirs(c)
    rel = re.search(r"(^|[\s'\"/\\=(])(\.harness[/\\]ledger|hooks[/\\](gate|targets|permissions)\.)", command)
    if PS_WRITE.search(command) and (any(norm(d) in t or norm(d).replace(norm(HOME), "~") in t for d in prot) or rel):
        return deny(PROTECT_MSG)
    if VAULT_READ.search(command) and (c["kc"] in command or in_scope(cwd, c)):
        return deny("금고(자격 증명 관리자·키체인) 값은 읽지 않습니다. 비밀값 이름·있는지만 보려면 `jarvis secret list`.")
    if in_scope(cwd, c):
        if PS_DELETE.search(command):
            return deny("PowerShell 로 지우지 않습니다. 지우는 대신 휴지통으로: Move-Item 대상 ~/.Trash/ "
                        "(Bash 도구로 하면 rm 규칙(임시·작업 폴더·휴지통 아래만)이 그대로 걸립니다)")
        if PS_STOP.search(command):
            return deny("서비스·작업·프로세스를 멈추지 않습니다. 이 비서의 서비스는 지킴이가 다시 띄웁니다.")
    return None


def judge_powershell(command, cwd, c, agent_id=""):
    r = judge_ps_text(command, cwd, c)
    return r or judge_bash(command, cwd, c, agent_id)  # git push·배포 명령 등은 bash 와 같은 규칙


def judge_file(tool, inp, cwd, c):
    p = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    if not p:
        return None
    real = absp(p, cwd)
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit") and any(under(real, d) for d in protected_dirs(c)):
        return deny(PROTECT_MSG)
    if tool == "Read" and in_scope(cwd, c) and (SECRET_FILE.search(real) or any(real.startswith(d) for d in SECRET_DIRS)):
        return deny("비밀값 파일은 열지 않습니다. 프로그램이 값을 쓰면 엔진이 금고에서 넣습니다.")
    return None


PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M)


def judge_patch(patch, cwd, c):
    """Codex 의 apply_patch(패치 글 하나로 파일을 만들고 고치고 지움). 패치 머리의 파일 자리를 하나씩 본다.
    - 울타리(<홈>/hooks/·장부·엔진) 안의 파일은 만들거나 고치거나 지우지 않는다(Claude 의 Edit·Write 와 같음).
    - 'Delete File' 은 영구 삭제라 Jarvis 세션 안에서는 rm 과 같은 규칙(임시·작업 폴더·휴지통 아래만)."""
    if not isinstance(patch, str):
        return None
    prot = protected_dirs(c)
    for m in PATCH_FILE.finditer(patch):
        kind, p = m.group(1) or "Move", (m.group(2) or m.group(3) or "").strip()
        if not p:
            continue
        real = absp(p, cwd)
        if any(under(real, d) for d in prot):
            return deny(PROTECT_MSG)
        if kind == "Delete" and in_scope(cwd, c):
            r = judge_rm(["rm", p], cwd, c)
            if r:
                return r
    return None


def shell_text(cmd):
    """Bash 도구의 명령 글. Codex 는 목록(["bash", "-lc", "…"])으로 줄 때가 있어 글 하나로 맞춘다."""
    if isinstance(cmd, str):
        return cmd
    if isinstance(cmd, (list, tuple)) and all(isinstance(a, str) for a in cmd) and cmd:
        if len(cmd) >= 3 and cmdname(cmd[0]) in ("bash", "sh", "zsh") and cmd[1] in ("-c", "-lc", "-ic"):
            return cmd[2]
        return " ".join(shlex.quote(a) for a in cmd)
    return None


def judge_mcp(tool, cwd, c):
    if not in_scope(cwd, c):
        return None
    g = c["gate"]
    if any(re.search(a, tool) for a in g.get("mcp_allow") or []):
        return None
    name = tool.split("__")[-1].lower()
    draft = "draft" in name and not re.search(r"(^|_)(send|delete)(_|$)", name)  # 초안 만들기·고치기는 됨
    if (MCP_SEND.search(name) and not draft) or any(re.search(p, tool) for p in g.get("mcp_block") or []):
        return deny("밖으로 보내거나 영구히 지우는 도구는 직접 쓰지 않습니다. 초안까지 만들고, 보내기는 승인 요청으로"
                    "(스킬 send-mail·approval-request).")
    return None


def judge(event):
    c = load()
    tool = event.get("tool_name") or ""
    inp = event.get("tool_input") or {}
    if isinstance(inp, str):  # 글 하나로 오는 도구 입력(Codex apply_patch 의 패치 글 등)
        inp = {"command": inp}
    if not isinstance(inp, dict):
        return None
    cwd = event.get("cwd") or ""
    if tool == "Bash":
        cmd = shell_text(inp.get("command") if "command" in inp else inp.get("cmd"))
        return judge_bash(cmd, cwd, c, event.get("agent_id") or "") if cmd is not None else None
    if tool == "PowerShell":
        cmd = inp.get("command")
        return judge_powershell(cmd, cwd, c, event.get("agent_id") or "") if isinstance(cmd, str) else None
    if tool.startswith("mcp__"):
        return judge_mcp(tool, cwd, c)
    if tool == "write_stdin":  # Codex: 이미 띄운 프로그램(셸 등)에 넣는 글. 셸 명령처럼 본다(빈 글은 출력 기다리기라 통과)
        chars = next((inp[k] for k in ("chars", "input", "text") if isinstance(inp.get(k), str)), "")
        return judge_bash(chars.strip(), cwd, c, event.get("agent_id") or "") if chars.strip() else None
    patch = inp.get("command")
    if tool == "apply_patch" or (isinstance(patch, str) and "*** Begin Patch" in patch):
        return judge_patch(patch if isinstance(patch, str) else inp.get("patch") or inp.get("input"), cwd, c)
    return judge_file(tool, inp, cwd, c)


def read_stdin():
    """훅 입력(JSON)은 UTF-8 이다. 윈도 콘솔 코드 페이지(cp949 등)로 읽지 않게 바이트로 받아 푼다."""
    data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read()
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data


def utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def main():
    utf8_stdout()
    try:
        event = json.loads(read_stdin())
        if not isinstance(event, dict):
            return 0
    except (ValueError, TypeError):
        return 0
    try:
        r = judge(event)
    except Exception as x:  # noqa: BLE001  문지기가 고장 나도 일은 멈추지 않는다(허용 쪽)
        print(f"문지기 오류(무시): {x}", file=sys.stderr)
        return 0
    if r:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": r[0],
                                                 "permissionDecisionReason": r[1]}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
