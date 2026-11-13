# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0"]
# ///
# -*- coding: utf-8 -*-
"""제안서·보고서 PPT 정적 검수: references/qa.md 가운데 파일만 보고 정해지는 항목을 확인한다.

사용법:
  uv run scripts/check_deck.py DECK.pptx [--final] [--json]
  python3 scripts/check_deck.py DECK.pptx          # python-pptx 가 이미 있는 환경

검사 항목 (ERROR 는 고쳐야 넘긴다, WARN 은 사람이 보고 판단한다):
  page      하단 오른쪽 쪽 번호가 실제 슬라이드 순서와 같은지 (두 자리 표기는 WARN)
  progress  본문 제목의 (i/n): 장의 본문이 한 장이면 (1/1) 금지, 여러 장이면 n = 실제 본문 장수, i 차례
  toc       목차 쪽수는 시작 쪽 하나(5-7, 5~7 금지), 그 쪽에 해당 장명이 실제로 있는지
  font      테마·run 글꼴이 Pretendard 인지, 한자(前 등)는 대체 글꼴 run 으로 분리됐는지
  wrap      한글 run 에 한국어 언어 표시(lang=ko-KR)가 없으면 WARN (PowerPoint 가 단어 중간에서 끊을 수 있음)
  unit      표·차트 단위 표기가 '(단위: 백만원)' 꼴인지, 반올림·출처 등이 붙지 않았는지, 개체 우측 상단인지
  office    '11곳' 같은 숫자+곳 표기 (사무소 수라면 '개소') WARN
  bounds    슬라이드 밖으로 나간 개체
  compat    PowerPoint 복구 경고를 부르는 구조: 차트 축 참조, 같은 슬라이드의 개체 id 중복, 선 요소 순서
  final     --final(고객 배포본): 노란 형광표시는 ERROR, 발표자 노트·문서 속성은 WARN 으로 나열

결과는 stdout, 사용법 오류는 stderr. 종료 코드: 0 = ERROR 없음, 1 = ERROR 있음, 2 = 실행 불가(파일·의존성).
글자 넘침은 render_preview.py, 실제 PowerPoint 열기·렌더·단어 분리는 powerpoint_check.py 가 맡는다.
"""
import argparse
import json
import re
import sys
import zipfile

try:
    from pptx import Presentation
    from pptx.util import Emu
    from lxml import etree
except ImportError:
    sys.stderr.write("python-pptx 가 없습니다. `uv run scripts/check_deck.py DECK.pptx` 로 실행하거나 "
                     "`pip install python-pptx` 가 된 환경의 python 으로 실행하세요.\n")
    sys.exit(2)

FONT = "Pretendard"
NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
HANGUL = re.compile(r"[가-힣]")
CJK_IDEO = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
PROGRESS = re.compile(r"\((\d+)\s*/\s*(\d+)\)")
PAGE_RANGE = re.compile(r"^\s*\d+\s*[-–—~∼]\s*\d+\s*$")
UNIT_OK = re.compile(r"^\(단위:\s?[^()·,;:]+\)$")
UNIT_EXTRA = re.compile(r"반올림|절사|출처|자료|기준|결산")
OFFICE_GOT = re.compile(r"\d+\s*곳")


def inch(v):
    return Emu(v).inches if v is not None else 0.0


def norm(s):
    return re.sub(r"\s+", " ", s.replace("\v", " ")).strip()


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, sid, rule, msg):
        self.items.append({"level": level, "slide": sid, "rule": rule, "msg": msg})

    def err(self, sid, rule, msg):
        self.add("ERROR", sid, rule, msg)

    def warn(self, sid, rule, msg):
        self.add("WARN", sid, rule, msg)


def text_shapes(slide):
    """(shape, text) for every shape with text, groups flattened."""
    out = []

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == 6:  # group
                walk(sh.shapes)
            elif sh.has_text_frame and sh.text_frame.text.strip():
                out.append(sh)
    walk(slide.shapes)
    return out


def slide_text(slide):
    parts = [sh.text_frame.text for sh in text_shapes(slide)]
    for sh in slide.shapes:
        if sh.has_table:
            for row in sh.table.rows:
                for c in row.cells:
                    parts.append(c.text_frame.text)
    return norm(" ".join(parts))


def max_size(sh):
    sizes = [r.font.size.pt for p in sh.text_frame.paragraphs for r in p.runs if r.font.size]
    return max(sizes) if sizes else 0


def body_title(slide):
    """The content-slide title: 20~32pt text near y 0.85in, full text."""
    cands = [sh for sh in text_shapes(slide)
             if 0.6 <= inch(sh.top) <= 1.2 and 20 <= max_size(sh) <= 32]
    if not cands:
        return None
    sh = sorted(cands, key=lambda s: inch(s.top))[0]
    return norm(sh.text_frame.text)


def is_toc(slide):
    return any(norm(sh.text_frame.text) in ("목차", "CONTENTS", "Contents") and inch(sh.top) < 1.6
               for sh in text_shapes(slide))


def is_divider(slide):
    """Section divider: big chapter number (\\d\\d, >=40pt) or big 'Executive Summary', no body title."""
    for sh in text_shapes(slide):
        t = norm(sh.text_frame.text)
        if max_size(sh) >= 40 and (re.fullmatch(r"\d{2}", t) or t.replace(" ", "").lower() == "executivesummary"):
            return True
    return False


def check_pages(prs, rep):
    W, H = inch(prs.slide_width), inch(prs.slide_height)
    for sid, s in enumerate(prs.slides, 1):
        nums = [sh for sh in text_shapes(s)
                if re.fullmatch(r"\d{1,3}", sh.text_frame.text.strip())
                and inch(sh.top) > H - 0.8 and inch(sh.left) > W * 0.7]
        if not nums:
            if sid > 1:
                rep.warn(sid, "page", "하단 쪽 번호를 찾지 못했다 (표지·마무리 장이면 무시)")
            continue
        t = nums[0].text_frame.text.strip()
        if int(t) != sid:
            rep.err(sid, "page", f"쪽 번호 '{t}' 이(가) 실제 순서 {sid} 와 다르다")
        elif len(t) != 2 and sid < 100:
            rep.warn(sid, "page", f"쪽 번호 '{t}' — 원형은 두 자리 표기(예: {sid:02d})")


def check_progress(prs, rep):
    chapters, cur = [], None
    for sid, s in enumerate(prs.slides, 1):
        if is_divider(s):
            cur = {"start": sid, "bodies": []}
            chapters.append(cur)
            continue
        if cur is None or is_toc(s):
            continue
        t = body_title(s)
        if t:
            cur["bodies"].append((sid, t))
    for ch in chapters:
        bodies = ch["bodies"]
        n_body = len(bodies)
        marked = [(sid, t, PROGRESS.search(t)) for sid, t in bodies]
        for i, (sid, t, m) in enumerate(marked, 1):
            if not m:
                continue
            a, b = int(m.group(1)), int(m.group(2))
            if n_body == 1:
                rep.err(sid, "progress", f"장의 본문이 한 장인데 진행 번호가 있다: '{t}' → '{PROGRESS.sub('', t).replace('  ', ' ')}'")
            elif b != n_body:
                rep.err(sid, "progress", f"'{t}': n={b} 이지만 이 장(간지 {ch['start']}쪽)의 실제 본문은 {n_body}장")
            elif a != i:
                rep.err(sid, "progress", f"'{t}': i={a} 이지만 이 장에서 {i}번째 본문")
        if n_body >= 2 and not any(m for _, _, m in marked):
            rep.warn(ch["start"], "progress",
                     f"간지 {ch['start']}쪽 장의 본문이 {n_body}장인데 제목에 (i/n) 이 없다 — '장명(i/n) - 세부 주제' 체계를 쓰는 문서면 붙인다")


def check_toc(prs, rep):
    slides = list(prs.slides)
    for sid, s in enumerate(slides, 1):
        if not is_toc(s):
            continue
        items = [sh for sh in text_shapes(s) if inch(sh.top) > 1.8 and inch(sh.top) < 6.9]
        rows = {}
        for sh in items:
            key = round(inch(sh.top) / 0.15)
            rows.setdefault(key, []).append(sh)
        for key in sorted(rows):
            row = sorted(rows[key], key=lambda x: inch(x.left))
            if len(row) < 2:
                continue
            page_t = row[-1].text_frame.text.strip()
            name = norm(" ".join(x.text_frame.text for x in row[1:-1])) if len(row) > 2 else norm(row[0].text_frame.text)
            if PAGE_RANGE.match(page_t):
                rep.err(sid, "toc", f"목차 '{name}' 쪽수 '{page_t}' — 범위 없이 시작 쪽 하나만 적는다")
                continue
            if not re.fullmatch(r"\d{1,3}", page_t):
                continue
            p = int(page_t)
            if p < 1 or p > len(slides):
                rep.err(sid, "toc", f"목차 '{name}' 쪽수 {p} 가 슬라이드 수({len(slides)})를 벗어난다")
                continue
            target = slide_text(slides[p - 1]).replace(" ", "")
            if name and name.replace(" ", "") not in target:
                rep.err(sid, "toc", f"목차 '{name}' → {p}쪽에 그 장명이 없다 (시작 쪽이 바뀌었거나 장명이 다르다)")


def run_fonts(r):
    rPr = r._r.find(f"{{{NS['a']}}}rPr")
    faces = {}
    if rPr is not None:
        for tag in ("latin", "ea", "cs"):
            el = rPr.find(f"a:{tag}", NS)
            if el is not None and el.get("typeface"):
                faces[tag] = el.get("typeface")
    return faces


def check_fonts(prs, rep):
    # theme
    for rel in prs.slide_masters[0].part.rels.values():
        if rel.reltype.endswith("/theme"):
            root = etree.fromstring(rel.target_part.blob)
            for tag in ("majorFont", "minorFont"):
                f = root.find(f".//a:{tag}", NS)
                if f is None:
                    continue
                for sub in ("latin", "ea"):
                    el = f.find(f"a:{sub}", NS)
                    face = el.get("typeface") if el is not None else ""
                    if face != FONT:
                        rep.err(0, "font", f"테마 {tag}/{sub} 글꼴이 '{face}' — Pretendard 로 지정한다")
    for sid, s in enumerate(prs.slides, 1):
        runs = []
        for sh in text_shapes(s):
            for p in sh.text_frame.paragraphs:
                runs += p.runs
        for sh in s.shapes:
            if sh.has_table:
                for row in sh.table.rows:
                    for c in row.cells:
                        for p in c.text_frame.paragraphs:
                            runs += p.runs
        bad, ideo = set(), []
        for r in runs:
            t = r.text
            if not t.strip():
                continue
            faces = run_fonts(r)
            only_ideo = all(CJK_IDEO.match(ch) or ch.isspace() for ch in t)
            if only_ideo:
                continue  # 前 같은 한자 run 은 대체 글꼴 허용
            for tag, face in faces.items():
                if face != FONT and not face.startswith("+"):
                    bad.add(f"{tag}={face}")
            if CJK_IDEO.search(t) and faces.get("ea", FONT) == FONT:
                ideo.append(t.strip()[:20])
        if bad:
            rep.err(sid, "font", f"Pretendard 가 아닌 글꼴: {', '.join(sorted(bad))}")
        if ideo:
            rep.err(sid, "font", f"한자가 Pretendard run 안에 있다(□로 보일 수 있음): {ideo[:3]} — 한자만 대체 글꼴 run 으로 나눈다")


def check_wrap(prs, rep):
    """PowerPoint(Mac) 는 run 언어가 ko-KR 일 때만 한글을 낱말 단위로 줄바꿈한다. 언어 표시가 없으면
    (기본 en-US) 글자 단위로 끊어 '검/토' 가 생긴다. eaLnBrk 속성은 효과가 없다(PowerPoint for Mac 시험)."""
    slides = []
    for sid, s in enumerate(prs.slides, 1):
        frames = [sh.text_frame for sh in text_shapes(s)]
        for sh in s.shapes:
            if sh.has_table:
                frames += [c.text_frame for row in sh.table.rows for c in row.cells]
        untagged = 0
        for tf in frames:
            for p in tf.paragraphs:
                if len(p.text.strip()) < 8:
                    continue
                for r in p.runs:
                    if HANGUL.search(r.text):
                        rPr = r._r.find(f"{{{NS['a']}}}rPr")
                        if rPr is None or not (rPr.get("lang") or "").startswith("ko"):
                            untagged += 1
                            break
        if untagged:
            slides.append(sid)
    if slides:
        rng = ", ".join(str(x) for x in slides[:12]) + (" …" if len(slides) > 12 else "")
        rep.warn(0, "wrap", f"{len(slides)}개 슬라이드({rng})의 한글 run 에 한국어 언어 표시(lang=ko-KR)가 없다 — "
                            "PowerPoint 가 단어 중간에서 줄을 바꿀 수 있다. 수동 줄바꿈으로 맞춘 사용자 파일이면 그대로 두고, "
                            "powerpoint_check.py 로 실제 분리 여부를 확인한다")


def check_units(prs, rep):
    for sid, s in enumerate(prs.slides, 1):
        objs = [sh for sh in s.shapes if sh.has_table or sh.has_chart]
        labels = []
        for sh in text_shapes(s):
            for p in sh.text_frame.paragraphs:
                if "단위" in p.text:
                    labels.append((sh, norm(p.text)))
        for sh in objs:
            if sh.has_table:
                for row in sh.table.rows:
                    for c in row.cells:
                        if "단위" in c.text_frame.text:
                            rep.warn(sid, "unit", f"표 안에 단위 표기 '{norm(c.text_frame.text)[:30]}' — 공통 단위면 표 우측 상단으로 옮긴다")
        for sh, t in labels:
            if not UNIT_OK.match(t) or UNIT_EXTRA.search(t):
                rep.err(sid, "unit", f"단위 표기 '{t[:60]}' — '(단위: 백만원)' 처럼 단위만 괄호에 넣고 반올림·출처·기준은 분리한다")
                continue
            if not objs:
                continue
            l_bottom, l_right = inch(sh.top) + inch(sh.height), inch(sh.left) + inch(sh.width)
            below = [o for o in objs if inch(o.top) >= inch(sh.top) - 0.05]
            if not below:
                rep.warn(sid, "unit", f"단위 표기 '{t}' 가 표·차트 아래에 있다 — 개체 우측 상단에 둔다")
                continue
            o = min(below, key=lambda o: inch(o.top))
            o_right = inch(o.left) + inch(o.width)
            if l_bottom > inch(o.top) + 0.15 or abs(l_right - o_right) > 0.3:
                rep.warn(sid, "unit", f"단위 표기 '{t}' 가 표·차트 우측 상단 끝에 맞지 않다 (라벨 오른쪽 {l_right:.2f}in, 개체 오른쪽 {o_right:.2f}in)")


def check_office(prs, rep):
    for sid, s in enumerate(prs.slides, 1):
        hits = sorted(set(OFFICE_GOT.findall(slide_text(s))))
        if hits:
            rep.warn(sid, "office", f"{', '.join(hits[:4])} — 사무소 수라면 '개소'로 쓴다 (사람·고객 수면 무시)")


def check_bounds(prs, rep):
    W, H = inch(prs.slide_width), inch(prs.slide_height)
    for sid, s in enumerate(prs.slides, 1):
        for sh in s.shapes:
            if sh.left is None or sh.width is None:
                continue
            x, y, w, h = inch(sh.left), inch(sh.top), inch(sh.width), inch(sh.height)
            if x < -0.01 or y < -0.01 or x + w > W + 0.02 or y + h > H + 0.02:
                rep.err(sid, "bounds", f"'{sh.name}' 이(가) 슬라이드 밖으로 나간다 (x={x:.2f}, y={y:.2f}, w={w:.2f}, h={h:.2f})")


def check_compat(path, prs, rep):
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            rep.err(0, "compat", f"압축 파일 손상: {bad}")
        for name in z.namelist():
            if re.match(r"ppt/charts/chart\d+\.xml$", name):
                root = etree.fromstring(z.read(name))
                axes = {e.get("val") for tag in ("catAx", "valAx", "dateAx", "serAx")
                        for ax in root.iter(f"{{{NS['c']}}}{tag}")
                        for e in ax.findall("c:axId", NS)}
                plot = root.find(".//c:plotArea", NS)
                refs = set()
                if plot is not None:
                    for chart in plot:
                        if chart.tag.endswith("Chart"):
                            refs |= {e.get("val") for e in chart.findall("c:axId", NS)}
                missing = refs - axes
                if missing:
                    rep.err(0, "compat", f"{name}: 차트가 없는 축 id {sorted(missing)} 를 참조한다 (PowerPoint 복구 경고 원인)")
    for sid, s in enumerate(prs.slides, 1):
        ids = [el.get("id") for el in s._element.iter(f"{{{NS['p']}}}cNvPr")]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            rep.err(sid, "compat", f"같은 슬라이드에 개체 id 중복 {dup[:5]} (PowerPoint 복구 경고 원인)")
        for ln in s._element.iter(f"{{{NS['a']}}}ln"):
            tags = [c.tag.split("}")[1] for c in ln]
            if "extLst" in tags and tags.index("extLst") != len(tags) - 1:
                rep.err(sid, "compat", "선(a:ln) 안에서 extLst 뒤에 다른 요소가 있다 — 요소 순서 오류")


def check_final(prs, rep, final):
    for sid, s in enumerate(prs.slides, 1):
        hl = sum(1 for _ in s._element.iter(f"{{{NS['a']}}}highlight"))
        if hl:
            (rep.err if final else rep.warn)(sid, "final", f"형광표시 {hl}곳 — 사용자 작업본이면 두고, 고객 배포 사본에서는 지운다")
        if final and s.has_notes_slide:
            nt = s.notes_slide.notes_text_frame.text.strip()
            if nt:
                rep.warn(sid, "final", f"발표자 노트가 있다: '{norm(nt)[:50]}' — 고객 배포본에 작업 이력·출처 메모가 남지 않게 정리")
    if final:
        cp = prs.core_properties
        rep.warn(0, "final", f"문서 속성 확인: 제목='{cp.title}', 작성자='{cp.author}', 마지막 수정='{cp.last_modified_by}'")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="check_deck.py",
        description=__doc__.split("\n\n")[0] + "\n\n" + __doc__.split("\n\n")[2],
        epilog="예: uv run scripts/check_deck.py out/제안서_v2.pptx\n    uv run scripts/check_deck.py out/보고서_배포본.pptx --final --json",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pptx", help="검수할 .pptx 파일")
    ap.add_argument("--final", action="store_true", help="고객 배포본 기준: 형광표시는 ERROR, 노트·문서 속성 나열")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    a = ap.parse_args(argv)
    if not a.pptx.lower().endswith(".pptx"):
        sys.stderr.write(f"'{a.pptx}' 는 .pptx 가 아니다. .ppt·.key·.pdf 는 PowerPoint 에서 .pptx 로 저장한 뒤 검사한다.\n")
        return 2
    try:
        prs = Presentation(a.pptx)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"'{a.pptx}' 를 열 수 없다: {e.__class__.__name__}: {e}. 경로와 파일 형식(.pptx)을 확인한다.\n")
        return 2
    rep = Report()
    check_pages(prs, rep)
    check_progress(prs, rep)
    check_toc(prs, rep)
    check_fonts(prs, rep)
    check_wrap(prs, rep)
    check_units(prs, rep)
    check_office(prs, rep)
    check_bounds(prs, rep)
    check_compat(a.pptx, prs, rep)
    check_final(prs, rep, a.final)
    n_err = sum(1 for i in rep.items if i["level"] == "ERROR")
    n_warn = len(rep.items) - n_err
    if a.json:
        print(json.dumps({"file": a.pptx, "slides": len(prs.slides), "errors": n_err, "warnings": n_warn,
                          "items": rep.items}, ensure_ascii=False, indent=1))
    else:
        for i in sorted(rep.items, key=lambda i: (i["level"] != "ERROR", i["slide"])):
            where = f"s{i['slide']:02d}" if i["slide"] else "덱"
            print(f"{i['level']:5} {where} [{i['rule']}] {i['msg']}")
        print(f"결과: 슬라이드 {len(prs.slides)}장, 오류 {n_err}, 경고 {n_warn} — "
              + ("통과(경고는 눈으로 판단)" if n_err == 0 else "오류를 고친 새 사본으로 다시 검사"))
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
