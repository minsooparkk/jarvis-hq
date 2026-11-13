"""운영체제 층. 나머지 코드는 sys.platform 을 직접 보지 않고 여기 current() 가 주는 것을 쓴다.

숨기는 것
- 서비스(오래 도는 프로그램): 등록·해제·상태·다시 켜기. 맥 launchd, 윈도 작업 스케줄러.
- 비밀값 금고: 넣기·읽기·지우기·있는지. 맥 키체인, 윈도 자격 증명 관리자.
- `jarvis` 명령 바로가기, 폴더 연결(.claude/skills → ../skills), 휴지통으로 보내기.
- 셸(bash)·venv 파이썬·claude 실행 파일 찾기, 프로세스 멈추기, 파일 잠금, 시스템 시간대 읽기.

명령 실행기(run, subprocess.run 과 같은 모양)를 주입받는다. 시험은 가짜 실행기로 어떤 명령·파일을 만드는지 본다.
표준 라이브러리만 쓴다(설치 스크립트가 맥·윈도 기본 파이썬으로 이것을 불러 쓴다). Linux 등은 '지원 안 함' 을 알린다.
"""

import sys

from .base import Platform, ServiceSpec, Unsupported  # noqa: F401

SUPPORTED = ("mac", "windows")


def kind(sys_platform=None):
    p = sys_platform or sys.platform
    if p == "darwin":
        return "mac"
    if p in ("win32", "cygwin"):
        return "windows"
    return "unsupported"


def get(name, **kw):
    """이름으로 고른다(시험에서 맥 위에서 윈도 구현을 가짜 실행기로 돌릴 때)."""
    if name == "mac":
        from .mac import Mac
        return Mac(**kw)
    if name == "windows":
        from .windows import Windows
        return Windows(**kw)
    from .base import UnsupportedPlatform
    return UnsupportedPlatform(**kw)


def current(**kw):
    return get(kind(), **kw)
