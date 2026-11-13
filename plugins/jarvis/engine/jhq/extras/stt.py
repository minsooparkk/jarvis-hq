"""선택 모듈: 녹음 받아쓰기 `jarvis stt <파일>`. 맥 안에서만(ffmpeg + whisper.cpp 의 whisper-cli). 녹음은 밖으로 나가지 않는다.

필요한 것(없으면 무엇을 깔지 알리고 멈춘다):
  brew install ffmpeg whisper-cpp
  모델 파일 하나(예: ggml-large-v3-turbo-q5_0.bin)를 <엔진>/models/ 에 두거나 config.json 의 extras.stt.model 에 경로
설정(config.json, 선택): {"extras": {"stt": {"ffmpeg": "...", "whisper": "...", "model": "...", "lang": "ko"}}}

  jarvis stt doctor              준비됐는지
  jarvis stt 녹음.m4a [--lang ko] [--out 폴더]   → 글 파일 경로를 찍는다
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import config

SILENT_DB = -45.0
MADE_UP = ("시청해 주셔서 감사합니다", "구독과 좋아요", "다음 영상에서 만나요")
SETUP = ("받아쓰기 준비가 안 됐습니다. 대표 맥에서 한 번: `brew install ffmpeg whisper-cpp`, 그리고 whisper.cpp 모델 파일 하나"
         "(예: ggml-large-v3-turbo-q5_0.bin)를 {models} 에 두세요. 다른 자리면 config.json 의 extras.stt.model 에 경로를 적습니다.")


def tools(cfg=None):
    cfg = cfg or config.load()
    s = (cfg.get("extras") or {}).get("stt") or {}
    models = config.engine_dir() / "models"
    model = s.get("model")
    if not model and models.is_dir():
        found = sorted(models.glob("ggml-*.bin"))
        model = str(found[0]) if found else None
    return {"ffmpeg": s.get("ffmpeg") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg",
            "whisper": s.get("whisper") or shutil.which("whisper-cli") or "/opt/homebrew/bin/whisper-cli",
            "model": model, "lang": s.get("lang") or "ko", "models": str(models)}


def missing(t):
    out = [k for k in ("ffmpeg", "whisper") if not Path(str(t[k])).exists()]
    if not t["model"] or not Path(t["model"]).exists():
        out.append("model")
    return out


def transcribe(src, t, out_dir, timeout=3600):
    src = Path(src).expanduser().resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jarvis-stt-") as tmp:
        wav = Path(tmp) / "in.wav"
        conv = subprocess.run([t["ffmpeg"], "-nostdin", "-hide_banner", "-y", "-i", str(src), "-vn", "-ar", "16000", "-ac", "1",
                               "-c:a", "pcm_s16le", "-af", "volumedetect", str(wav)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if conv.returncode != 0 or not wav.exists():
            raise RuntimeError("소리 변환 실패: " + conv.stderr[-300:])
        loud = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", conv.stderr)
        if loud and (loud.group(1) == "-inf" or float(loud.group(1)) < SILENT_DB):
            raise RuntimeError("무음으로 보여 받아쓰지 않았습니다")
        base = Path(tmp) / "out"
        run = subprocess.run([t["whisper"], "-m", t["model"], "-l", t["lang"], "-np", "-otxt", "-of", str(base), "-f", str(wav)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        txt = base.with_suffix(".txt")
        if run.returncode != 0 or not txt.exists():
            raise RuntimeError("받아쓰기 실패: " + run.stderr[-300:])
        said = txt.read_text(encoding="utf-8", errors="replace").strip()
    core = " ".join(said.split()).strip(" .!")
    if not core or any(core.startswith(m) and len(core) <= len(m) + 3 for m in MADE_UP):
        raise RuntimeError("받아쓴 말이 없습니다(무음이거나 지어낸 인사만 나옴)")
    dest = out_dir / f"{src.stem}.txt"
    dest.write_text(said + "\n", encoding="utf-8")
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jarvis stt", description="녹음 받아쓰기(맥 안 whisper.cpp)")
    ap.add_argument("file", help="녹음 파일 또는 doctor")
    ap.add_argument("--lang")
    ap.add_argument("--out", help="글 파일을 둘 폴더(기본 <홈>/.harness/work/stt)")
    a = ap.parse_args(argv)
    cfg = config.load()
    t = tools(cfg)
    if a.lang:
        t["lang"] = a.lang
    gone = missing(t)
    if a.file == "doctor":
        print("준비됨" if not gone else "없음: " + ", ".join(gone))
        if gone:
            print(SETUP.format(models=t["models"]))
        return 0 if not gone else 3
    if gone:
        print(SETUP.format(models=t["models"]) + "\n없는 것: " + ", ".join(gone), file=sys.stderr)
        return 3
    out = Path(a.out).expanduser() if a.out else config.Paths(cfg).work / "stt"
    try:
        print(transcribe(a.file, t, out))
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0
