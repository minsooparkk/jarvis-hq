# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0", "pymupdf>=1.24"]
# ///
# -*- coding: utf-8 -*-
"""실제 Microsoft PowerPoint(macOS)로 PPTX 를 열어 검수한다. LibreOffice·근사 미리보기로 대신하지 않는 항목.

사용법:
  uv run scripts/powerpoint_check.py DECK.pptx [--out DIR] [--png] [--dpi 80] [--timeout 120]

하는 일 (원본 파일은 건드리지 않는다. 사본을 PowerPoint 샌드박스 폴더에 두고 연다):
  1. PowerPoint 로 연다. 열자마자 뜨는 창(복구 경고·권한 요청 등)이 있으면 문구를 적고 '취소'한 뒤 실패로 끝낸다.
  2. 슬라이드 수가 python-pptx 로 센 수와 같은지 본다.
  3. PowerPoint 로 PDF 를 내보낸다 (실제 렌더). --out 폴더에 <이름>.powerpoint.pdf 로 둔다.
  4. PDF 에 쓰인 글꼴이 Pretendard(한자 대체: Malgun Gothic·Apple SD Gothic Neo) 밖이면 알린다.
  5. 한글 단어가 줄 끝에서 갈라진 곳(예: '전산시스/템')을 PPTX 원문과 대조해 찾는다.
  6. --png 면 쪽마다 PNG 를 만든다(눈 검수용). PowerPoint 를 이 스크립트가 켰으면 끝에 닫는다.

결과는 stdout, 진행·진단은 stderr. 종료 코드: 0 = 문제 없음, 1 = 문제 있음,
2 = 실행 불가(파일 없음), 3 = 이 환경에 PowerPoint 가 없음(macOS 가 아니거나 미설치) — 이때는 검수를
'PowerPoint 미확인'으로 적고 render_preview.py 결과만 근사치로 보고한다.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

APP = "Microsoft PowerPoint"
APP_PATH = "/Applications/Microsoft PowerPoint.app"
CONTAINER = os.path.expanduser("~/Library/Containers/com.microsoft.Powerpoint/Data/tmp/deck-check")
OK_FONTS = ("Pretendard", "MalgunGothic", "Malgun", "AppleSDGothicNeo")
HANGUL = re.compile(r"[가-힣]")


def log(msg):
    sys.stderr.write(msg + "\n")


def osa(script, timeout):
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"osascript {timeout}s 시간 초과"


def running():
    return subprocess.run(["pgrep", "-x", APP], capture_output=True).returncode == 0


def windows():
    """[(name, subrole)] of PowerPoint windows."""
    code, out, _ = osa(f'tell application "System Events" to tell process "{APP}" to get {{name, subrole}} of every window', 20)
    if code != 0 or not out:
        return []
    parts = [x.strip() for x in out.split(",")]
    half = len(parts) // 2
    return list(zip(parts[:half], parts[half:]))


def sheets_of(win):
    code, out, _ = osa(f'tell application "System Events" to tell process "{APP}" to get count of sheets of window "{win}"', 15)
    return int(out) if code == 0 and out.isdigit() else 0


def dialog_text(win, sheet=False):
    target = f'sheet 1 of window "{win}"' if sheet else f'window "{win}"'
    code, out, _ = osa(f'tell application "System Events" to tell process "{APP}" to get value of every static text of {target}', 20)
    return out if code == 0 else ""


def dismiss(win, sheet=False):
    target = f'sheet 1 of window "{win}"' if sheet else f'window "{win}"'
    for btn in ("취소", "Cancel", "아니요", "No", "확인", "OK"):
        code, _, _ = osa(f'tell application "System Events" to tell process "{APP}" to click button "{btn}" of {target}', 15)
        if code == 0:
            return btn
    return None


def check_dialogs(doc_stem, issues, before):
    """Only touch windows this run caused: new non-standard windows (dialogs) and sheets on our own document.
    Windows that existed before the run (e.g. the user's open documents) are never touched."""
    for name, sub in windows():
        if (name, sub) in before:
            continue
        if name.startswith(doc_stem):
            if sheets_of(name):
                txt = dialog_text(name, sheet=True)
                issues.append(f"문서 창의 시트: {txt[:160]} → '{dismiss(name, sheet=True) or '닫기 실패'}'")
            continue
        if sub != "AXStandardWindow":
            txt = dialog_text(name)
            issues.append(f"PowerPoint 창 '{name}': {txt[:160]} → '{dismiss(name) or '닫기 실패'}'")


def pptx_texts(path):
    """Per slide: (compact text without whitespace, list mapping compact index -> 'space follows?')."""
    from pptx import Presentation
    prs = Presentation(path)
    pages = []
    for s in prs.slides:
        parts = []
        for sh in s.shapes:
            if sh.has_text_frame:
                parts.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                parts += [c.text_frame.text for row in sh.table.rows for c in row.cells]
        orig = "\n".join(parts)
        compact, gap_after = [], []
        for ch in orig:
            if ch.isspace() or ch == "\v":
                if gap_after:
                    gap_after[-1] = True
            else:
                compact.append(ch)
                gap_after.append(False)
        pages.append(("".join(compact), gap_after))
    return len(prs.slides), pages


def mid_word_breaks(pdf_path, pages):
    """PowerPoint 의 PDF 는 낱말 사이 공백을 빼고 줄을 나눈다. 줄 끝·다음 줄 첫 글자가 모두 한글이고,
    PPTX 원문에서 그 두 글자 사이에 공백·줄바꿈이 없으면 단어 중간에서 끊긴 것이다."""
    import pymupdf
    found = []
    doc = pymupdf.open(pdf_path)
    for pno, page in enumerate(doc):
        if pno >= len(pages):
            break
        compact, gap_after = pages[pno]
        for b in page.get_text("dict")["blocks"]:
            lines = ["".join(sp["text"] for sp in ln["spans"]) for ln in b.get("lines", [])]
            for a, c in zip(lines, lines[1:]):
                a2, c2 = re.sub(r"\s", "", a), re.sub(r"\s", "", c)
                if not a2 or not c2 or a.endswith((" ", "-")):
                    continue
                if not (HANGUL.match(a2[-1]) and HANGUL.match(c2[0])):
                    continue
                tail, head = a2[-8:], c2[:4]
                key = tail + head
                hits = [m.start() for m in re.finditer(re.escape(key), compact)]
                if hits and all(not gap_after[h + len(tail) - 1] for h in hits):
                    found.append((pno + 1, f"{tail[-4:]}/{head}"))
    return found, len(doc)


def pdf_fonts(pdf_path):
    import pymupdf
    names = set()
    for page in pymupdf.open(pdf_path):
        for f in page.get_fonts():
            names.add(f[3].split("+")[-1])
    return sorted(names)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="powerpoint_check.py",
        description="Microsoft PowerPoint(macOS)로 열기·복구 경고·슬라이드 수·PDF 렌더·글꼴·한글 단어 분리를 확인한다.",
        epilog="예: uv run scripts/powerpoint_check.py out/제안서_v2.pptx --out out/qa --png",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pptx", help="검수할 .pptx")
    ap.add_argument("--out", help="PDF·PNG 를 둘 폴더 (기본: PPTX 와 같은 폴더)")
    ap.add_argument("--png", action="store_true", help="PDF 각 쪽을 PNG 로도 저장 (눈 검수용)")
    ap.add_argument("--dpi", type=int, default=80, help="PNG 해상도 (기본 80)")
    ap.add_argument("--timeout", type=int, default=120, help="PowerPoint 한 동작의 최대 대기 초 (기본 120)")
    ap.add_argument("--from-pdf", metavar="PDF", help="PowerPoint 를 다시 열지 않고, 이미 PowerPoint 로 내보낸 PDF 만 분석")
    a = ap.parse_args(argv)

    src = os.path.abspath(a.pptx)
    if not os.path.isfile(src) or not src.lower().endswith(".pptx"):
        log(f"'{a.pptx}' 가 없거나 .pptx 가 아니다. 경로를 확인한다.")
        return 2
    if a.from_pdf:
        if not os.path.isfile(a.from_pdf):
            log(f"--from-pdf '{a.from_pdf}' 가 없다.")
            return 2
        n_slides, pages = pptx_texts(src)
        breaks, n_pages = mid_word_breaks(a.from_pdf, pages)
        issues = [f"PDF 쪽 수 {n_pages} ≠ 슬라이드 수 {n_slides}"] if n_pages != n_slides else []
        issues += [f"s{p:02d} 한글 단어가 줄 끝에서 갈라졌다: '{w}'" for p, w in breaks]
        odd = [f for f in pdf_fonts(a.from_pdf) if not f.startswith(OK_FONTS)]
        if odd:
            issues.append(f"PDF 에 Pretendard 밖의 글꼴: {', '.join(odd)}")
        for i in issues:
            print(f"ERROR {i}")
        print(f"결과(PDF 분석만): 슬라이드 {n_slides}장, 문제 {len(issues)}건")
        return 1 if issues else 0
    if sys.platform != "darwin" or not os.path.isdir(APP_PATH):
        print("SKIP PowerPoint 를 찾지 못했다(macOS 의 /Applications/Microsoft PowerPoint.app 필요). "
              "PowerPoint 검수는 '미확인'으로 보고하고 render_preview.py 근사 결과를 따로 밝힌다.")
        return 3
    out_dir = os.path.abspath(a.out or os.path.dirname(src))
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    tag = f"deck-check-{uuid.uuid4().hex[:8]}"
    os.makedirs(CONTAINER, exist_ok=True)
    work = os.path.join(CONTAINER, tag + ".pptx")
    work_pdf = os.path.join(CONTAINER, tag + ".pdf")
    shutil.copy2(src, work)
    was_running = running()
    before = set(windows()) if was_running else set()
    issues = []
    n_slides, page_words = pptx_texts(src)
    try:
        log(f"PowerPoint 로 여는 중: {os.path.basename(src)}")
        code, _, err = osa(f'tell application "{APP}" to open POSIX file "{work}"', a.timeout)
        time.sleep(3)
        check_dialogs(tag, issues, before)
        if code != 0:
            issues.append(f"열기 실패 또는 시간 초과: {err}")
        code, out, err = osa(f'tell application "{APP}" to get count of slides of presentation "{tag}.pptx"', 30)
        if code != 0:
            issues.append(f"열린 문서를 찾지 못했다: {err}")
            raise RuntimeError
        if int(out) != n_slides:
            issues.append(f"PowerPoint 슬라이드 수 {out} ≠ 파일 슬라이드 수 {n_slides}")
        log("PDF 로 내보내는 중 (실제 렌더)")
        code, _, err = osa(f'tell application "{APP}" to save presentation "{tag}.pptx" in POSIX file "{work_pdf}" as save as PDF', a.timeout)
        check_dialogs(tag, issues, before)
        if code != 0 or not os.path.isfile(work_pdf):
            issues.append(f"PDF 내보내기 실패: {err}")
    except RuntimeError:
        pass
    finally:
        osa(f'tell application "{APP}" to close presentation "{tag}.pptx" saving no', 30)
        check_dialogs(tag, issues, before)
        if not was_running:
            osa(f'tell application "{APP}" to quit', 30)
        if os.path.exists(work):
            os.remove(work)

    pdf_out = None
    if os.path.isfile(work_pdf):
        pdf_out = os.path.join(out_dir, stem + ".powerpoint.pdf")
        shutil.move(work_pdf, pdf_out)
        breaks, n_pages = mid_word_breaks(pdf_out, page_words)
        if n_pages != n_slides:
            issues.append(f"PDF 쪽 수 {n_pages} ≠ 슬라이드 수 {n_slides}")
        for pno, w in breaks:
            issues.append(f"s{pno:02d} 한글 단어가 줄 끝에서 갈라졌다: '{w}' — 상자 폭·문구·의미 단위 줄바꿈으로 고친다")
        odd = [f for f in pdf_fonts(pdf_out) if not f.startswith(OK_FONTS)]
        if odd:
            issues.append(f"PDF 에 Pretendard 밖의 글꼴: {', '.join(odd)} — 글꼴 미설치·대체 여부 확인")
        if a.png:
            import pymupdf
            png_dir = os.path.join(out_dir, stem + ".powerpoint-png")
            os.makedirs(png_dir, exist_ok=True)
            for i, page in enumerate(pymupdf.open(pdf_out), 1):
                page.get_pixmap(dpi=a.dpi).save(os.path.join(png_dir, f"s{i:02d}.png"))
            print(f"PNG {png_dir}")

    for i in issues:
        print(f"ERROR {i}")
    if pdf_out:
        print(f"PDF {pdf_out}")
    print(f"결과: 슬라이드 {n_slides}장, PowerPoint 문제 {len(issues)}건 — "
          + ("통과(차트·배치는 PDF·PNG 로 눈 검수)" if not issues else "고친 새 사본으로 다시 검사"))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
