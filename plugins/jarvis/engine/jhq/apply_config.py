"""실행기 대상 'config-apply' 의 몸통: 승인받은 설정 파일 하나를 <홈>/hooks/ 에 넣는다.

<홈>/hooks/(문지기 gate.json · 실행 대상 targets.yaml · 권한 permissions.json)는 Jarvis 가 직접 고치지 못한다(문지기가 막음).
고칠 때는 Jarvis 가 새 내용을 JSON({"file": "targets.yaml", "content": "…"})으로 만들어 이 대상으로 승인을 요청하고,
대표가 승인하면 실행기가 옛 파일을 <홈>/.harness/state/backup/<시각>/ 에 남기고 새 내용으로 바꾼다.
permissions.json 이 바뀌면 권한도 다시 만든다(jarvis perms build).
"""

import json
import os
import shutil
import sys
from pathlib import Path

from . import config, perms

ALLOWED = ("gate.json", "targets.yaml", "permissions.json")


def apply(payload_path, paths=None):
    paths = paths or config.Paths()
    p = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    name = str(p.get("file") or "")
    if name not in ALLOWED:
        raise SystemExit(f"바꿀 수 있는 파일은 {', '.join(ALLOWED)} 뿐입니다: {name}")
    content = str(p.get("content") or "")
    if name.endswith(".json"):
        json.loads(content)  # 모양이 틀리면 여기서 멈춘다
    else:
        import yaml
        yaml.safe_load(content)
    dest = paths.home / "hooks" / name
    if dest.exists():
        back = paths.state / "backup" / config.now(paths.cfg).strftime("%Y%m%d-%H%M%S")
        back.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dest, back / name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    if name == "permissions.json":
        code, msg = perms.build(paths, owner_approval=f"승인 요청 {os.environ.get('JARVIS_REQUEST_ID', '')}")
        print(msg)
        if code:
            raise SystemExit(code)
    print(f"{name} 을(를) 바꿨습니다(옛 파일은 .harness/state/backup/ 에).")


def main():
    src = os.environ.get("JARVIS_PAYLOAD")
    if not src or not os.environ.get("JARVIS_REQUEST_ID"):
        print("실행기 전용 입구입니다(승인된 요청에서만).", file=sys.stderr)
        return 2
    apply(src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
