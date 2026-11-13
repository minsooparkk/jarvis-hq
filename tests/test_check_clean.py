"""개인정보 검사 스크립트: 이 저장소는 깨끗하고, 심어 둔 것은 잡는다."""

import subprocess
import sys

from conftest import REPO

CHECK = REPO / "scripts" / "check_clean.py"


def run(*args):
    return subprocess.run([sys.executable, str(CHECK), *args], capture_output=True, text=True)


def test_repo_is_clean():
    r = run()
    assert r.returncode == 0, r.stdout


def test_catches_planted(tmp_path):
    # 이 시험 파일 자체가 검사에 걸리지 않게 심을 글은 실행 때 이어 붙인다
    planted = "연락: someone" + "@" + "corp-mail.io\n번호 010" + "-1234-5678\nIP 10.1." + "2.3\n"
    (tmp_path / "a.md").write_text(planted, encoding="utf-8")
    (tmp_path / "b.py").write_text('KEY = "sk-' + 'ant-abc123"\n', encoding="utf-8")
    r = run(str(tmp_path))
    assert r.returncode == 1
    for what in ("메일 주소", "휴대전화 번호", "IP 주소", "Anthropic 키"):
        assert what in r.stdout


def test_extra_terms_file_and_allow(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    (d / "x.txt").write_text("우리 회사 이름은 가나다상사 입니다. a@example.com 은 예시\n", encoding="utf-8")
    terms = tmp_path / "terms.txt"
    terms.write_text("가나다상사\n", encoding="utf-8")
    assert run(str(d)).returncode == 0
    r = run(str(d), "--terms-file", str(terms))
    assert r.returncode == 1 and "고유 낱말" in r.stdout


def test_hash_term_line():
    r = subprocess.run([sys.executable, str(CHECK), "--hash-term"], input="무언가", capture_output=True, text=True)
    assert r.stdout.strip().startswith('("') and "무언가" not in r.stdout


def test_scoped_allow_only_in_its_place(tmp_path):
    """자리를 좁힌 허락은 그 자리(해시로 적은 경로) 안에서 그 낱말에만 먹는다."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cc", CHECK)
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    place, term = cc.SCOPED_ALLOW[0]
    hits = [t for t in cc.TERMS if t[0] == term]
    assert hits and place != term
    # 허락된 자리의 실제 파일은 깨끗하다(저장소 검사가 통과), 같은 글을 다른 자리에 두면 걸린다
    src = None
    for p in cc.files(REPO):
        rel = p.relative_to(REPO).as_posix()
        if p.is_file() and cc.scoped_terms(cc.TERMS, rel) != cc.TERMS and p.suffix in (".md", ".json"):
            src = p
            break
    assert src is not None
    d = tmp_path / "repo"
    (d / "elsewhere").mkdir(parents=True)
    (d / "elsewhere" / "x.md").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    r = run(str(d))
    assert r.returncode == 1 and "고유 낱말" in r.stdout
    # 허락된 자리 안이라도 다른 꼴(메일 주소)은 그대로 잡는다
    rel = src.relative_to(REPO)
    (d / rel).parent.mkdir(parents=True, exist_ok=True)
    (d / rel).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    import shutil
    shutil.rmtree(d / "elsewhere")
    assert run(str(d)).returncode == 0
    (d / rel).write_text(src.read_text(encoding="utf-8") + "\n연락 someone" + "@" + "corp-mail.io\n", encoding="utf-8")
    r = run(str(d))
    assert r.returncode == 1 and "메일 주소" in r.stdout
