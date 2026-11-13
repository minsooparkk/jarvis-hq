#!/usr/bin/env python3
"""개인정보·비밀값 검사. 저장소 전체(파일 내용과 파일 이름)에서 원본 운영 환경의 고유 문자열과 비밀값 꼴이 남았는지 본다.
하나라도 걸리면 끝 코드 1(CI 처럼 실패). 표준 라이브러리만.

  python3 scripts/check_clean.py [폴더]          검사(기본: 이 저장소)
  python3 scripts/check_clean.py --hash-term     표준입력의 낱말 하나를 목록 줄로 바꿔 찍는다(낱말 원문은 저장소에 남기지 않음)
  python3 scripts/check_clean.py --terms-file F  목록에 더할 낱말 파일(한 줄에 하나, 저장소 밖에 둔다)

고유 낱말(사람·회사·서비스 이름, 원본 경로 등)은 원문 대신 소금 친 SHA-256 앞자리로만 적어 둔다. 이 파일을 배포해도
무엇을 찾는지 드러나지 않게 하려는 것이다. 찾을 때는 글의 모든 자리를 같은 길이로 잘라 같은 방법으로 해시해 맞춰 본다.
"""

import argparse
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

SALT = b"jarvis-hq-clean-v1|"
# (해시 앞 24자, 글자 수, 방식). 방식: sub = 어디든, word = 앞뒤가 영문·숫자가 아닐 때만. 대소문자는 가리지 않는다.
TERMS = (
    ("ae0041d7d7cd4f042200abe0", 3, "sub"),
    ("1d4db7c9aeac058209233088", 2, "sub"),
    ("8df83841cb31ef5f8ee4772b", 6, "sub"),
    ("17396178a255bdb2f1513f7e", 6, "sub"),
    ("323a46a9fc8f3c57f66d9e0f", 6, "sub"),
    ("dbc4eda2c68f56bc6a5d2096", 6, "sub"),
    ("8d16fd186622819134154892", 2, "sub"),
    ("e0c8036a0912ad71c98b4dfd", 7, "sub"),
    ("1e5d8a37749e909aea31c9e6", 4, "word"),
    ("ec93de0ded8be21017f70ad3", 6, "sub"),
    ("c7b9301245f28fb6202dd3cd", 9, "sub"),
    ("1581bb3f0062301bb9167467", 12, "sub"),
    ("e03fc4d271f4413ce86feb6d", 3, "sub"),
    ("e135cd023f275d00ef23bb14", 3, "sub"),
    ("ef9114c84dcc916027e764d0", 10, "sub"),
    ("02a24f0d0416651f0b2b3b46", 2, "sub"),
    ("15f3b1f117c236319cfbf2bc", 13, "sub"),
    ("58e93049f5767e39e33f7b52", 5, "sub"),
    ("79d873604d9f20b1baff902a", 3, "sub"),
    ("907d1c3d8bf3839274046ea9", 3, "sub"),
    ("426261d105c7d63ffeed513f", 3, "sub"),
    ("281530fd4de67ee03821ebbf", 5, "sub"),
    ("45f15fda761fb697055c5278", 8, "sub"),
    ("5b011ab584a8e74c39e46402", 8, "sub"),
    ("e6f57861028838acc4970672", 8, "sub"),
    ("b726678ec71cf8489029acc3", 10, "sub"),
    ("5376dc791b24396f5780cd33", 7, "sub"),
)
ALLOW = ("minsooparkk",)  # 배포 저장소 소유자 이름(설치 명령에 꼭 필요). 이 낱말 통째로만 허락
# 자리를 좁힌 허락: (자리 해시, 낱말 해시). 자리는 저장소 안 경로(파일 또는 폴더, / 로 이음)를 낱말과 같은 방법으로 해시한 것.
# 그 자리 안에서 그 낱말 하나만 봐준다(다른 낱말·비밀값 꼴은 그대로 검사). 자리 이름에 낱말이 들어 있을 수 있어 자리도 해시로 적는다.
# 주인이 일부러 넣은 공개 스킬과 그 MCP 설정에 제품 이름·공개 주소가 들어 있어서다. 새로 더할 때는 자리를 가장 좁게.
SCOPED_ALLOW = (
    ("866513754100304616cb276e", "c7b9301245f28fb6202dd3cd"),  # 세무 검토 스킬 폴더: 제품 이름·공개 MCP 주소
    ("902f9c01465ac9f092027487", "c7b9301245f28fb6202dd3cd"),  # 플러그인 .mcp.json: 그 스킬의 MCP 서버 공개 주소
    # 한국어 글쓰기 규칙의 출처 표기: 남의 Threads 계정 이름 안에 검사 낱말(6자)과 같은 글자가 들어 있다. 걸린 두 파일만
    ("4b7b4fc6573bb9a19d00ebeb", "8df83841cb31ef5f8ee4772b"),  # template/rules/11-한국어-문장.md
    ("c23ff22e11bac90d7bcb1f54", "8df83841cb31ef5f8ee4772b"),  # template/docs/threads-ai-style-sources.md
)
PATTERNS = (
    ("텔레그램 봇 토큰", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}")),
    ("텔레그램 그룹 번호", re.compile(r"(?<![\d.])-100\d{8,}(?!\d)")),
    ("텔레그램 사용자 번호 꼴(9~11자리 숫자)", re.compile(r"(?<![\w.\-/])[1-9]\d{8,10}(?![\w])")),
    ("Slack 채널·사용자 ID", re.compile(r"\b[CUWGD]0[A-Z0-9]{7,11}\b")),
    ("32자리 16진수(계정 ID 꼴)", re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{32}(?![0-9a-fA-F])")),
    ("IP 주소", re.compile(r"(?<![\d.])(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")),
    ("휴대전화 번호", re.compile(r"(?<!\d)01[016789][-. ]?\d{3,4}[-. ]?\d{4}(?!\d)")),
    ("전화번호", re.compile(r"(?<!\d)0(?:2|[3-6]\d)[-. ]\d{3,4}[-. ]\d{4}(?!\d)|\+\d{1,3}[- ]\d{1,4}[- ]\d{3,4}[- ]\d{4}")),
    ("메일 주소", re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    ("Anthropic 키", re.compile(r"sk-ant-[A-Za-z0-9_-]+")),
    ("Slack 토큰", re.compile(r"xox[abprs]-[A-Za-z0-9-]+")),
    ("GitHub 토큰", re.compile(r"ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}")),
    ("AWS 키", re.compile(r"AKIA[0-9A-Z]{16}")),
)
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules"}
WORD = re.compile(r"[a-z0-9]")


def norm(s):
    return unicodedata.normalize("NFC", s).lower()


def term_hash(term):
    return hashlib.sha256(SALT + norm(term).encode()).hexdigest()[:24]


def mask(text):
    for a in ALLOW:
        text = re.sub(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", "#" * len(a), text)
    return text


def scoped_terms(terms, rel):
    """rel(저장소 안 경로, / 로 이음) 자리에서 봐줄 낱말을 뺀 목록."""
    parts = rel.split("/")
    places = {term_hash("/".join(parts[:i])) for i in range(1, len(parts) + 1)}
    skip = {h for place, h in SCOPED_ALLOW if place in places}
    return [t for t in terms if t[0] not in skip] if skip else terms


def find_terms(text, terms):
    """(줄 번호, 글자 수) 목록."""
    low = mask(norm(text))
    hits = []
    by_len = {}
    for h, n, mode in terms:
        by_len.setdefault(n, {})[h] = mode
    for n, table in by_len.items():
        for i in range(0, max(0, len(low) - n + 1)):
            w = low[i:i + n]
            if w[0] in " \n\t#":
                continue
            h = hashlib.sha256(SALT + w.encode()).hexdigest()[:24]
            mode = table.get(h)
            if not mode:
                continue
            if mode == "word" and ((i > 0 and WORD.match(low[i - 1])) or (i + n < len(low) and WORD.match(low[i + n]))):
                continue
            hits.append((low.count("\n", 0, i) + 1, n))
    return hits


def scan_text(text, terms):
    out = []
    for line, n in find_terms(text, terms):
        out.append((line, f"고유 낱말({n}자)"))
    masked = mask(text)
    for name, rx in PATTERNS:
        for m in rx.finditer(masked):
            out.append((masked.count("\n", 0, m.start()) + 1, name))
    return out


def files(root):
    for p in sorted(Path(root).rglob("*")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--hash-term", action="store_true")
    ap.add_argument("--terms-file")
    a = ap.parse_args(argv)
    if a.hash_term:
        t = sys.stdin.read().strip()
        mode = "word" if len(t) <= 4 and t.isascii() else "sub"
        print(f'    ("{term_hash(t)}", {len(norm(t))}, "{mode}"),')
        return 0
    terms = list(TERMS)
    if a.terms_file:
        for ln in Path(a.terms_file).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                terms.append((term_hash(ln.strip()), len(norm(ln.strip())), "sub"))
    root = Path(a.root).resolve()
    problems = []
    for p in files(root):
        rel = p.relative_to(root).as_posix()
        here = scoped_terms(terms, rel)
        for _line, what in scan_text(rel, here):
            problems.append(f"{rel} (파일 이름): {what}")
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            text = p.read_bytes().decode("latin-1")
        for line, what in scan_text(text, here):
            problems.append(f"{rel}:{line}: {what}")
    if problems:
        print(f"걸린 곳 {len(problems)}개:")
        print("\n".join(problems))
        return 1
    print(f"깨끗합니다({root}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
