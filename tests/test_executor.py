"""실행기: 봉인·서명·한 번만 실행·바뀌면 실행 안 함."""

import json
import os
import subprocess
from datetime import datetime

import pytest

from conftest import add_target, seal_key
from jhq import executor, outbox

COLS = {"summary": "시험 실행", "why": "", "details": ""}


def counting_target(paths, name="count", **extra):
    body = {"이름": "횟수 세기", "실행": [f"echo x >> '{paths.home}/runs.txt'"], "창": "always"}
    body.update(extra)
    add_target(paths, name, body)
    return paths.home / "runs.txt"


def request(paths, target="count", inp=None):
    con = executor.connect(paths)
    try:
        n, _ = executor.new_request(paths, con, target, inp, "아무것도 안 함", dict(COLS))
        return n, executor.get(con, n)
    finally:
        con.close()


def approve(paths, key, n, seal=None):
    con = executor.connect(paths)
    try:
        r = executor.get(con, n)
        return executor.decide(paths, con, f"{executor.rid(n)}|{seal or r['seal']}", "승인됨", key)
    finally:
        con.close()


def state(paths, n):
    con = executor.connect(paths)
    try:
        return executor.get(con, n)
    finally:
        con.close()


def test_approved_runs_once(env):
    cfg, paths = env
    key = seal_key(cfg)
    runs = counting_target(paths)
    n, r = request(paths)
    assert r["state"] == "봉인" and len(r["seal"]) == 64
    assert executor.tick(paths, key) == 0  # 승인 전에는 아무것도 안 함
    assert approve(paths, key, n) is None
    assert state(paths, n)["state"] == "승인"
    executor.tick(paths, key)
    assert state(paths, n)["state"] == "완료"
    assert runs.read_text().count("x") == 1
    executor.tick(paths, key)
    assert runs.read_text().count("x") == 1
    con = outbox.connect(paths)
    assert any("끝났습니다" in o["text"] for o in outbox.due(con))


def test_crash_between_marker_and_finish_is_not_rerun(env):
    cfg, paths = env
    key = seal_key(cfg)
    runs = counting_target(paths)
    n, _ = request(paths)
    approve(paths, key, n)
    executor.tick(paths, key)
    con = executor.connect(paths)
    con.execute("update requests set state='승인' where id=?", (n,))  # 끝을 적기 전에 죽은 것처럼
    con.commit()
    con.close()
    executor.tick(paths, key)
    assert state(paths, n)["state"] == "불확실"
    assert runs.read_text().count("x") == 1


def test_recover_crashed_marks_uncertain(env):
    cfg, paths = env
    counting_target(paths)
    n, _ = request(paths)
    con = executor.connect(paths)
    con.execute("update requests set state='실행 중' where id=?", (n,))
    con.commit()
    con.close()
    executor.recover_crashed(paths)
    assert state(paths, n)["state"] == "불확실"


def test_same_seal_not_requested_twice(env):
    _cfg, paths = env
    counting_target(paths)
    request(paths)
    with pytest.raises(executor.ExecError, match="이미 기다리고"):
        request(paths)


def test_shown_seal_mismatch_refused(env):
    cfg, paths = env
    key = seal_key(cfg)
    counting_target(paths)
    n, _ = request(paths)
    err = approve(paths, key, n, seal="0" * 64)
    assert err and "바뀌었습니다" in err
    assert state(paths, n)["state"] == "실행 안 함"


def test_target_changed_before_approval_refused(env):
    cfg, paths = env
    key = seal_key(cfg)
    counting_target(paths)
    n, _ = request(paths)
    counting_target(paths, 창="always", 확인="true")  # 대상 설정이 바뀜
    err = approve(paths, key, n)
    assert err and "대상 설정" in err
    assert state(paths, n)["state"] == "실행 안 함"


def test_target_changed_after_approval_not_run(env):
    cfg, paths = env
    key = seal_key(cfg)
    runs = counting_target(paths)
    n, _ = request(paths)
    approve(paths, key, n)
    counting_target(paths, 실행=[f"echo y >> '{paths.home}/runs.txt'"])
    executor.tick(paths, key)
    r = state(paths, n)
    assert r["state"] == "실행 안 함" and "봉인" in r["result"]
    assert not runs.exists()


def test_input_copy_changed_after_approval_not_run(env, tmp_path):
    cfg, paths = env
    key = seal_key(cfg)
    add_target(paths, "with-input", {"이름": "입력 받기", "입력": "필수", "실행": ["cat \"$JARVIS_PAYLOAD\""], "창": "always"})
    src = tmp_path / "in.txt"
    src.write_text("보낼 내용")
    n, r = request(paths, "with-input", str(src))
    approve(paths, key, n)
    staged = paths.ledger / json.loads(r["payload"])["input"]["path"]
    os.chmod(staged, 0o600)
    staged.write_text("바꿔치기")
    executor.tick(paths, key)
    assert state(paths, n)["state"] == "실행 안 함"


def test_input_required(env):
    _cfg, paths = env
    add_target(paths, "with-input", {"이름": "입력", "입력": "필수", "실행": ["true"]})
    with pytest.raises(executor.ExecError, match="입력 파일"):
        request(paths, "with-input")


def test_forged_or_missing_signature_refused(env):
    cfg, paths = env
    key = seal_key(cfg)
    runs = counting_target(paths)
    n, _ = request(paths)
    con = executor.connect(paths)
    con.execute("update requests set state='승인', approval_sig='deadbeef' where id=?", (n,))
    con.commit()
    con.close()
    executor.tick(paths, key)
    assert state(paths, n)["state"] == "실행 안 함"
    assert not runs.exists()


def test_signature_needs_real_key(env):
    cfg, paths = env
    key = seal_key(cfg)
    runs = counting_target(paths)
    n, _ = request(paths)
    approve(paths, "다른 열쇠", n)  # 다른 열쇠로 서명
    executor.tick(paths, key)
    assert state(paths, n)["state"] == "실행 안 함"
    assert not runs.exists()


def test_pause_blocks_everything(env):
    cfg, paths = env
    key = seal_key(cfg)
    runs = counting_target(paths)
    n, _ = request(paths)
    approve(paths, key, n)
    paths.pause.write_text("멈춤")
    executor.tick(paths, key)
    assert state(paths, n)["state"] == "승인" and not runs.exists()
    paths.pause.unlink()
    executor.tick(paths, key)
    assert state(paths, n)["state"] == "완료"


def test_window_waits(env):
    cfg, paths = env
    key = seal_key(cfg)
    runs = counting_target(paths, 창="05-07")
    n, _ = request(paths)
    approve(paths, key, n)
    noon = datetime(2026, 1, 5, 12, 0)
    executor.tick(paths, key, now=noon)
    r = state(paths, n)
    assert r["state"] == "승인" and "05~07" in r["note"] and not runs.exists()
    executor.tick(paths, key, now=datetime(2026, 1, 5, 5, 30))
    assert state(paths, n)["state"] == "완료"


def test_double_decision_blocked_and_reject(env):
    cfg, paths = env
    key = seal_key(cfg)
    counting_target(paths)
    n, r = request(paths)
    con = executor.connect(paths)
    assert executor.decide(paths, con, f"{executor.rid(n)}|{r['seal']}", "거부됨", key) is None
    err = executor.decide(paths, con, f"{executor.rid(n)}|{r['seal']}", "승인됨", key)
    con.close()
    assert "이미" in err
    assert state(paths, n)["state"] == "거부"


def test_revise_keeps_note(env):
    cfg, paths = env
    key = seal_key(cfg)
    counting_target(paths)
    n, r = request(paths)
    con = executor.connect(paths)
    executor.decide(paths, con, f"{executor.rid(n)}|{r['seal']}", "수정 요청", key, note="제목을 바꿔")
    con.close()
    r = state(paths, n)
    assert r["state"] == "수정 요청" and r["decision_note"] == "제목을 바꿔"


def test_failure_not_retried(env):
    cfg, paths = env
    key = seal_key(cfg)
    add_target(paths, "fails", {"이름": "실패", "실행": [f"echo x >> '{paths.home}/f.txt'; exit 3"]})
    n, _ = request(paths, "fails")
    approve(paths, key, n)
    executor.tick(paths, key)
    executor.tick(paths, key)
    assert state(paths, n)["state"] == "실패"
    assert (paths.home / "f.txt").read_text().count("x") == 1


def test_repo_target_checks_worktree(env, tmp_path):
    cfg, paths = env
    key = seal_key(cfg)
    repo = tmp_path / "repo"
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "t")
    (repo / "app.txt").write_text("v1")
    g("add", ".")
    g("commit", "-qm", "v1")
    add_target(paths, "site", {"이름": "사이트", "저장소": str(repo), "브랜치": "main", "경로": ["app.txt"],
                               "실행": ["cat app.txt > deployed.txt"]})
    n, _ = request(paths, "site")
    approve(paths, key, n)
    (repo / "app.txt").write_text("v2 몰래")
    executor.tick(paths, key)
    r = state(paths, n)
    assert r["state"] == "실행 안 함" and "저장 안 된 변경" in r["result"]
    (repo / "app.txt").write_text("v1")
    n2, _ = request(paths, "site")
    approve(paths, key, n2)
    executor.tick(paths, key)
    assert state(paths, n2)["state"] == "완료"
    assert (repo / "deployed.txt").read_text() == "v1"


def test_approval_text_is_built_from_seal(env):
    _cfg, paths = env
    counting_target(paths)
    n, r = request(paths)
    text, value = executor.approval_text(paths, r)
    assert value == f"{executor.rid(n)}|{r['seal']}"
    assert "승인 요청" in text and "⟦작업용⟧" in text and "횟수 세기" in text


def test_parse_rid():
    assert executor.parse_rid("R-0005") == 5
    assert executor.parse_rid("#요청12") == 12
    assert executor.parse_rid("7") == 7
