"""윈도 작업 스케줄러가 띄우는 입구(창 없는 pythonw.exe 로 돈다).

작업 스케줄러는 작업에 환경변수·로그 파일을 적을 수 없어서, 설치 스크립트가 만든 설정 JSON(<엔진>/services/<이름>.json)을
읽어 환경변수·작업 폴더·PATH 를 맞추고, 표준출력·오류를 로그 파일로 돌린 뒤 엔진 모듈(jhq.daemon 등)을 돌린다.
pythonw 에는 표준출력이 없어서(None) 로그로 돌리지 않으면 print·logging 이 사라지거나 멈춘다.

  pythonw.exe <엔진>/engine/jhq/platform/winlaunch.py <엔진>/services/<이름>.json
"""

import json
import os
import runpy
import sys


def prepare(spec, environ=None):
    """환경변수 사전을 고친다(시험에서 따로 부름)."""
    env = os.environ if environ is None else environ
    env.update({k: str(v) for k, v in (spec.get("env") or {}).items()})
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = spec["pythonpath"] + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    extra = [p for p in spec.get("path_prepend") or [] if p]
    if extra:
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH") or ""])
    return env


def main(argv=None):
    argv = sys.argv if argv is None else argv
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]  # 이 폴더의 base.py 등이 다른 import 를 가리지 않게
    with open(argv[1], encoding="utf-8") as f:
        spec = json.load(f)
    prepare(spec)
    sys.path.insert(0, spec["pythonpath"])
    os.makedirs(os.path.dirname(spec["log"]), exist_ok=True)
    log = open(spec["log"], "a", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = sys.stderr = log
    os.chdir(spec["cwd"])
    sys.argv = [spec["module"]] + list(spec.get("args") or [])
    runpy.run_module(spec["module"], run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
