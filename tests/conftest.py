"""시험 공통: 임시 HOME·엔진 자리·가짜 키체인. 실제 launchd·키체인·텔레그램은 건드리지 않는다."""

import importlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugins" / "jarvis"
ENGINE = PLUGIN / "engine"
sys.path.insert(0, str(ENGINE))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """임시 HOME 아래 엔진 설정과 Jarvis 홈(템플릿 hooks 포함)을 만든다. (cfg, paths) 를 돌려준다."""
    home = tmp_path / "home"
    home.mkdir()
    engine = home / ".jarvis-hq"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JARVIS_HQ_DIR", str(engine))
    monkeypatch.setenv("JARVIS_HQ_FAKE_KEYCHAIN", str(tmp_path / "keychain.json"))
    monkeypatch.delenv("JARVIS_HQ_AGENT", raising=False)
    jhome = home / "jarvis"
    (jhome / "hooks").mkdir(parents=True)
    for f in ("targets.yaml", "gate.json", "permissions.json"):
        shutil.copy(PLUGIN / "template" / "hooks" / f, jhome / "hooks" / f)
    engine.mkdir()
    (engine / "config.json").write_text(json.dumps({"home": str(jhome), "telegram": {"owner_id": 42}}))
    from jhq import config, secrets
    importlib.reload(config)
    cfg = config.load()
    paths = config.Paths(cfg).ensure()
    secrets.put(secrets.SEAL, "k" * 64, cfg)
    return cfg, paths


def add_target(paths, name, body):
    """targets.yaml 에 대상 하나를 더한다(시험용)."""
    import yaml
    doc = yaml.safe_load(paths.targets.read_text(encoding="utf-8"))
    doc["대상"][name] = body
    paths.targets.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


def seal_key(cfg):
    from jhq import secrets
    return secrets.get(secrets.SEAL, cfg)


os.environ.setdefault("TZ", "Asia/Seoul")
