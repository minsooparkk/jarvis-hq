"""설치 스크립트를 임시 HOME 에서 실제로 돌린다. launchd·키체인은 건드리지 않는다(가짜 키체인·launchctl 끔)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import PLUGIN

INSTALL = PLUGIN / "scripts" / "install.py"
SESSION = PLUGIN / "hooks" / "session_start.py"


@pytest.fixture
def box(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    env.update(HOME=str(home), JARVIS_HQ_DIR=str(home / ".jarvis-hq"), JARVIS_HQ_FAKE_KEYCHAIN=str(tmp_path / "kc.json"),
               JARVIS_HQ_NO_LAUNCHCTL="1")

    def run(*args, check=True):
        r = subprocess.run(["/usr/bin/python3", str(INSTALL), *args, "--json"], capture_output=True, text=True, env=env)
        if check:
            assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)

    def cli(*args):
        return subprocess.run([str(home / ".jarvis-hq" / "bin" / "jarvis"), *args], capture_output=True, text=True, env=env)

    run.home, run.env, run.cli, run.kc = home, env, cli, tmp_path / "kc.json"
    return run


BASE = ("--owner-name", "홍길동", "--owner-title", "대표", "--no-venv", "--python", sys.executable)


def test_fresh_install_lays_structure(box):
    rep = box(*BASE, "--dry-run")
    j = box.home / "jarvis"
    for f in ("CLAUDE.md", "RULES.md", "schedule.yaml", "skills/README.md", "hooks/gate.json", "hooks/targets.yaml",
              "hooks/permissions.json", ".harness/README.md", ".claude/settings.json"):
        assert (j / f).exists(), f
    rules = sorted(p.name for p in (j / "rules").glob("*.md"))
    assert rules[0].startswith("00-") and rules[-1].startswith("13-") and len(rules) == 14
    assert (j / "docs" / "threads-ai-style-sources.md").exists()
    for d in ("log", "decisions", "memory", "ledger", "state/logs", "work", "inbox"):
        assert (j / ".harness" / d).is_dir(), d
    assert os.readlink(j / ".claude" / "skills") == "../skills"
    assert "홍길동" in (j / "rules" / "00-나에-맞추기.md").read_text(encoding="utf-8")
    assert "{{" not in (j / "CLAUDE.md").read_text(encoding="utf-8")
    assert (box.home / ".jarvis-hq" / "engine" / "jhq" / "daemon.py").exists()
    assert (box.home / ".jarvis-hq" / "engine" / "hooks" / "gate.py").exists()
    assert os.readlink(box.home / ".local" / "bin" / "jarvis") == str(box.home / ".jarvis-hq" / "bin" / "jarvis")
    plists = sorted(p.name for p in (box.home / "Library" / "LaunchAgents").glob("*.plist"))
    assert plists == ["com.jarvis-hq.executor.plist", "com.jarvis-hq.jarvisd.plist", "com.jarvis-hq.watchdog.plist"]
    assert rep["telegram_token"] is False and "secret set telegram" in rep["next"][0]
    assert "dry-run" in rep["seal_key"] and not box.kc.exists()  # dry-run 은 키체인을 쓰지 않는다


def test_rerun_is_idempotent_and_keeps_user_files(box):
    box(*BASE)
    rules0 = box.home / "jarvis" / "rules" / "00-나에-맞추기.md"
    rules0.write_text("내가 고친 내용", encoding="utf-8")
    (box.home / "jarvis" / "CLAUDE.md").unlink()
    rep = box(*BASE)
    assert rep["created"] == ["CLAUDE.md"]  # 빠진 것만 채운다
    assert rules0.read_text(encoding="utf-8") == "내가 고친 내용"
    assert rep["engine"].startswith("같음")
    rep = box(*BASE)
    assert rep["created"] == [] and "rules/00-나에-맞추기.md" in rep["kept"]


def test_engine_update_keeps_backup(box):
    box(*BASE)
    marker = box.home / ".jarvis-hq" / "engine" / "jhq" / "local-change.txt"
    marker.write_text("옛 판")
    rep = box(*BASE)
    assert rep["engine"].startswith("새 판으로 바꿈")
    assert list((box.home / ".jarvis-hq" / "backup").rglob("local-change.txt"))


def test_seal_key_and_cli_work(box):
    box(*BASE)
    kc = json.loads(box.kc.read_text())
    assert len(kc["seal-key"]) == 64
    r = box.cli("secret", "list")
    assert "seal-key: 있음" in r.stdout and "telegram-bot-token: 없음" in r.stdout
    r = box.cli("exec", "targets")
    assert "hello" in r.stdout and "config-apply" in r.stdout
    r = box.cli("exec", "request", "--target", "hello", "--if-rejected", "안 함", "--결론", "시험")
    assert r.returncode == 0 and "R-0001" in r.stdout
    assert "R-0001" in box.cli("exec", "pending").stdout
    r = box.cli("perms", "check")
    assert r.returncode == 0, r.stderr


def test_ready_install_plans_launchd(box):
    box(*BASE)
    kc = json.loads(box.kc.read_text())
    kc["telegram-bot-token"] = "1:fake"
    box.kc.write_text(json.dumps(kc))
    rep = box(*BASE, "--telegram-owner-id", "42", "--dry-run")
    assert rep["telegram_owner_id"] and rep["services_dry_run"]
    assert any("bootstrap" in a for a in rep["services"])
    assert "안녕" in rep["next"][0]
    cfg = json.loads((box.home / ".jarvis-hq" / "config.json").read_text())
    assert cfg["telegram"]["owner_id"] == 42


def test_doctor_and_uninstall(box):
    box(*BASE)
    rep = box("--doctor", "--dry-run", check=False)
    names = {c["name"]: c["ok"] for c in rep["checks"]}
    assert names["홈 CLAUDE.md"] and names["엔진 코드"] and not names["텔레그램 토큰 telegram-bot-token(키체인)"]
    plan = box("--uninstall", "--dry-run")
    assert plan["trashed"] and (box.home / ".jarvis-hq").exists()
    rep = box("--uninstall")
    assert not (box.home / ".jarvis-hq").exists() and (box.home / "jarvis").exists()
    assert not (box.home / ".local" / "bin" / "jarvis").exists()
    trash = list((box.home / ".Trash").iterdir())
    assert any(p.name.startswith(".jarvis-hq") for p in trash)


@pytest.mark.parametrize("hook_python", ["/usr/bin/python3", sys.executable])
def test_session_start_hook(box, hook_python):
    box(*BASE)
    box.cli("exec", "request", "--target", "hello", "--if-rejected", "안 함", "--결론", "시험")
    ev = json.dumps({"cwd": str(box.home / "jarvis")})
    r = subprocess.run([hook_python, str(SESSION)], input=ev, capture_output=True, text=True, env=box.env)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "승인 기다리는 요청 1건" in ctx and "RULES.md" in ctx
    r = subprocess.run([hook_python, str(SESSION)], input=json.dumps({"cwd": "/"}), capture_output=True, text=True,
                       env=box.env)
    assert r.stdout.strip() == ""


def test_real_venv_install(box):
    """venv 를 실제로 만들고 PyYAML 을 받는다(인터넷 필요). 없으면 건너뜀."""
    if os.environ.get("JARVIS_TEST_NO_NETWORK"):
        pytest.skip("인터넷 없이 돌림")
    rep = box("--owner-name", "홍길동", "--dry-run", check=False)
    if "error" in rep:
        pytest.skip("venv·pip 실패(인터넷?): " + rep["error"][:100])
    py = Path(rep["python"])
    assert py.exists() and subprocess.run([str(py), "-c", "import yaml"]).returncode == 0
    assert box.cli("version").stdout.strip()


def test_session_start_reads_wal_ledger_without_side_files(box):
    """WAL 장부의 곁 파일(-wal·-shm)이 없어도 승인 대기 수를 읽는다(읽기 전용으로 못 여는 SQLite 판 대비, 회귀 시험)."""
    import sqlite3
    box(*BASE)
    ledger = box.home / "jarvis" / ".harness" / "ledger"
    db = ledger / "executor.db"
    con = sqlite3.connect(db)
    con.execute("pragma journal_mode=wal")
    con.execute("create table requests (id integer primary key, state text)")
    con.executemany("insert into requests(state) values (?)", [("봉인",), ("봉인",), ("승인",)])
    con.commit()
    con.execute("pragma wal_checkpoint(truncate)")
    con.close()
    for side in ("executor.db-wal", "executor.db-shm"):
        (ledger / side).unlink(missing_ok=True)
    ev = json.dumps({"cwd": str(box.home / "jarvis")})
    for py in ("/usr/bin/python3", sys.executable):
        r = subprocess.run([py, str(SESSION)], input=ev, capture_output=True, text=True, env=box.env)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "승인 기다리는 요청 2건 · 실행 기다리는 요청 1건" in ctx, (py, ctx)


def test_install_with_slack_messenger(box):
    rep = box(*BASE, "--messenger", "slack", "--dry-run")
    assert rep["messenger"] == "slack" and rep["messenger_token"] is False and "telegram_token" not in rep
    assert "slack-bot" in rep["next"][0] and "slack-app" in rep["next"][0]
    cfg = json.loads((box.home / ".jarvis-hq" / "config.json").read_text())
    assert cfg["messenger"] == "slack"
    kc = json.loads(box.kc.read_text()) if box.kc.exists() else {}
    kc.update({"slack-bot-token": "b", "slack-app-token": "a"})
    box.kc.write_text(json.dumps(kc))
    rep = box(*BASE, "--owner-id", "UOWNER1", "--dry-run")  # 메신저는 설정에 남은 slack 그대로
    assert rep["messenger_owner_id"] and rep["services_dry_run"] and any("bootstrap" in a for a in rep["services"])
    doc = box("--doctor", "--dry-run", check=False)
    names = {c["name"]: c["ok"] for c in doc["checks"]}
    assert names["대표 Slack 멤버 ID"] and names["Slack 토큰 slack-bot-token(키체인)"]
    r = box.cli("messenger", "status")
    assert r.returncode == 0 and "Slack" in r.stdout
