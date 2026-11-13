"""권한 빌드 `jarvis perms build|check|locked`.

엔진의 기본 층(넓은 허용 + 잠금 거부)과 사용자 층(<홈>/hooks/permissions.json)을 합쳐 <홈>/.claude/settings.json 을 만든다.
settings.json 은 직접 고치지 않는다(다음 build 때 덮임). 손으로 고친 흔적이 있으면 build 는 멈추고 알린다(--force 로만 덮음).

잠금: 아래 LOCKED 는 되돌릴 수 없는 일·비밀값 원문이라, 사용자 층의 'unlock' 에 넣어 빼려면 대표가 한 말을
--owner-approval "…" 에 적어야 한다(한 일 기록에 남는다).
문지기 훅(gate.py)은 플러그인이 켜져 있을 때도 돌지만, 플러그인을 꺼도 Jarvis 홈에서는 돌도록 엔진 사본을 여기에도 건다.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import config, worklog

LOCKED = (
    "Read(**/.env)",
    "Read(**/.env.*)",
    "Read(**/.dev.vars)",
    "Read(~/.ssh/**)",
    "Read(~/Library/Keychains/**)",
    "Bash(security find-generic-password:*)",
    "Bash(security find-internet-password:*)",
    "Bash(security dump-keychain:*)",
    "Bash(security export:*)",
    "Bash(git push --force:*)",
    "Bash(git push -f:*)",
    "Bash(docker volume prune:*)",
    "Bash(docker system prune:*)",
    "Bash(jarvis exec resume:*)",
    "Bash(jarvis secret set:*)",
    "Bash(jarvis secret delete:*)",
    "mcp__claude_ai_Gmail__send_message",
    "mcp__claude_ai_Gmail__reply",
    "mcp__claude_ai_Gmail__forward",
    "mcp__claude_ai_Microsoft_365__outlook_send_mail",
    "mcp__claude_ai_Microsoft_365__outlook_send_draft",
    "mcp__claude_ai_Microsoft_365__outlook_forward_mail",
    "mcp__claude_ai_Microsoft_365__outlook_batch_delete_messages",
    "mcp__claude_ai_Microsoft_365__teams_send_chat_message",
    "mcp__claude_ai_Microsoft_365__teams_send_channel_message",
    "mcp__claude_ai_Microsoft_365__teams_reply_channel_message",
    "mcp__claude_ai_Microsoft_365__sharepoint_delete_item",
    "mcp__claude_ai_Slack__slack_send_message",
    "mcp__claude_ai_Slack__slack_schedule_message",
)
BASE_ALLOW = ("Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebFetch", "WebSearch", "Agent", "TodoWrite", "Skill",
              # 플러그인에 실린 세법 MCP(읽기 전용 조회). 데몬의 `claude -p` 세션은 허용 규칙이 없으면 MCP 호출을 거부한다
              "mcp__plugin_jarvis_korea-tax-law__*")
GATE_MATCHER = "Bash|Read|Edit|Write|MultiEdit|NotebookEdit|mcp__.*"


def gate_hook():
    """엔진 사본의 문지기를 홈 settings.json 에도 건다. 훅 모양은 OS 층이 정한다(맥: 기본 python3 한 줄, 윈도: 엔진 파이썬 실행 형식)."""
    gate = config.ENGINE_ROOT / "hooks" / "gate.py"
    entry = config.plat().hook_entry(gate, sys.executable)
    return {"PreToolUse": [{"matcher": GATE_MATCHER, "hooks": [entry]}]}


def load_user(paths):
    try:
        return json.loads(Path(paths.permissions).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def build_doc(paths):
    """(settings 내용, 풀린 잠금 목록)."""
    user = load_user(paths)
    unlock = set(user.get("unlock") or [])
    locked = locked_rules()
    deny = [r for r in locked if r not in unlock]
    deny += [r for r in user.get("deny") or [] if r not in deny]
    allow = list(dict.fromkeys(list(BASE_ALLOW) + list(user.get("allow") or [])))
    perms = {"allow": allow, "deny": deny}
    if user.get("additionalDirectories"):
        perms["additionalDirectories"] = list(user["additionalDirectories"])
    doc = {"permissions": perms, "hooks": gate_hook()}
    return doc, sorted(unlock & set(locked))


def locked_rules():
    return tuple(LOCKED) + tuple(r for r in config.plat().locked_extra() if r not in LOCKED)


def render(doc):
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _stamp_file(paths):
    return Path(paths.settings).with_name(".settings.generated")


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def hand_edited(paths):
    s = Path(paths.settings)
    if not s.exists():
        return False
    try:
        return _stamp_file(paths).read_text(encoding="utf-8").strip() != _digest(s.read_text(encoding="utf-8"))
    except OSError:
        return True


def build(paths, owner_approval="", force=False):
    """돌려주는 것: (끝 코드, 안내 글)."""
    doc, unlocked = build_doc(paths)
    if unlocked and not owner_approval:
        return 2, ("잠금 거부가 풀려 있습니다(" + ", ".join(unlocked) + "). 대표가 시킨 말을 --owner-approval \"…\" 에 적어야 만듭니다.")
    if hand_edited(paths) and not force:
        return 3, ("settings.json 에 손으로 고친 곳이 있습니다. 고친 내용은 hooks/permissions.json 으로 옮기고 "
                   "--force 로 다시 만드세요(지금 파일은 settings.json.bak 으로 남깁니다).")
    s = Path(paths.settings)
    s.parent.mkdir(parents=True, exist_ok=True)
    text = render(doc)
    if s.exists() and force and hand_edited(paths):
        s.with_name("settings.json.bak").write_text(s.read_text(encoding="utf-8"), encoding="utf-8")
    changed = not s.exists() or s.read_text(encoding="utf-8") != text
    s.write_text(text, encoding="utf-8")
    _stamp_file(paths).write_text(_digest(text), encoding="utf-8")
    if changed:
        worklog.add("권한 설정 다시 만듦(jarvis perms build)", f"허용 {len(doc['permissions']['allow'])} · 거부 {len(doc['permissions']['deny'])}",
                    str(s) + (f" · 대표 승인: {owner_approval}" if owner_approval else ""), who="권한", paths=paths)
    return 0, f"만듦: 허용 {len(doc['permissions']['allow'])} · 거부 {len(doc['permissions']['deny'])}" + ("" if changed else " (바뀐 것 없음)")


def check(paths):
    doc, unlocked = build_doc(paths)
    s = Path(paths.settings)
    if not s.exists():
        return 1, "settings.json 이 없습니다(jarvis perms build)."
    if hand_edited(paths):
        return 1, "settings.json 에 손으로 고친 곳이 있습니다."
    if s.read_text(encoding="utf-8") != render(doc):
        return 1, "settings.json 이 지금 권한 파일과 다릅니다(jarvis perms build)."
    return 0, "맞음" + (f" (풀린 잠금: {', '.join(unlocked)})" if unlocked else "")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jarvis perms")
    ap.add_argument("cmd", choices=["build", "check", "locked"])
    ap.add_argument("--owner-approval", "--대표승인", dest="approval", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    paths = config.Paths()
    if a.cmd == "locked":
        print("\n".join(locked_rules()))
        return 0
    code, msg = build(paths, a.approval, a.force) if a.cmd == "build" else check(paths)
    print(msg, file=sys.stderr if code else sys.stdout)
    return code
