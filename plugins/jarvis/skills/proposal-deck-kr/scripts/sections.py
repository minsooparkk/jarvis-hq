# -*- coding: utf-8 -*-
"""Reusable sections: cover, contents, team, next step, firm profile (divider + 4 slides), thank-you.

All functions append slides to deck_lib.prs in call order. Firm values (name, people, contacts,
profile figures) come from deck_lib.FIRM (assets/firm.json or PROPOSAL_DECK_FIRM); without a
config every value is a placeholder such as '○○회계법인' or '[이름]'.
"""
from deck_lib import *

DEFAULT_PEOPLE = [
    {"name": "[이름]", "name_en": "NAME", "title": "DIRECTOR · CPA", "role": "공인회계사",
     "photo": "assets/person_placeholder_a.png", "crop": None,
     "career": ["[이전 소속·부서]", "[학력]"], "work": ["[대표 수행업무 1]", "[대표 수행업무 2]", "[대표 수행업무 3]"]},
    {"name": "[이름]", "name_en": "NAME", "title": "DIRECTOR · CPA", "role": "공인회계사",
     "photo": "assets/person_placeholder_b.png", "crop": None,
     "career": ["[이전 소속·부서]", "[학력]"], "work": ["[대표 수행업무 1]", "[대표 수행업무 2]", "[대표 수행업무 3]"]},
]
DEFAULT_PROFILE = {
    "as_of": "[기준일] 기준",
    "source": "[출처: 공시 자료명·접수번호·기준일]",
    "stats": [["000", "억원", "[최근 결산 매출]"], ["00", "명", "[공인회계사 수]"],
              ["000", "명", "[전체 인력]"], ["00", "개소", "[전국 사무소]"]],
    "info": [["설립", "[설립일]"], ["대표이사", "[이름]"], ["본점", "[주소]"],
             ["주요 업무", "[업무 영역]"], ["웹사이트", "[웹사이트]"]],
    "revenue": {"labels": ["Y-4", "Y-3", "Y-2", "Y-1", "Y"], "values": [100, 110, 125, 140, 150], "unit": "억원"},
    "mix": [["[업무 A]", 60], ["[업무 B]", 25], ["[업무 C]", 15]],
    "offices": [["[지역 1]", ["[사무소]", "[사무소]"]], ["[지역 2]", ["[사무소]"]], ["[지역 3]", ["[사무소]"]]],
}


def _with_han(text):
    """Split CJK ideographs (e.g. 前) into Malgun Gothic runs; Pretendard has no glyph for them."""
    runs, buf = [], ''
    for ch in text:
        if '一' <= ch <= '鿿':
            if buf: runs.append((buf, {})); buf = ''
            runs.append((ch, {'font': 'Malgun Gothic'}))
        else:
            buf += ch
    if buf: runs.append((buf, {}))
    return runs


def cover(eyebrow, title, sub_runs, date='20XX년 X월', bottom_line=None, notes=''):
    """Dark cover. sub_runs: list of (text, opts) runs, e.g. [('앞부분 ', {}), ('강조', {'color': C['blue2'], 'bold': True})]."""
    s = prs.slides.add_slide(BLANK); N[0] += 1
    dark_bg(s)
    logo(s, L, 0.62, 0.42)
    txt(s, L + 0.55, 0.62, 4, 0.42, FIRM['firm_name'], size=15, bold=True, color=C['white'], anchor=MSO_ANCHOR.MIDDLE)
    txt(s, L, 2.45, 8, 0.3, eyebrow, size=12, bold=True, color=C['sky'])
    txt(s, L, 2.85, 11.5, 1.0, title, size=46, bold=True, color=C['white'])
    if sub_runs:
        txt(s, L, 4.05, 11.5, 0.45, [sub_runs], size=20, color=C['onDark'])
    line(s, L, 6.25, CW, C['dline'])
    if bottom_line:
        txt(s, L, 6.45, 9.5, 0.3, bottom_line, size=12, color='9DB3CE')
    txt(s, SW - L - 3, 6.45, 3, 0.3, date, size=12, color='9DB3CE', align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = notes
    return s


def contents(items, notes=''):
    """Contents slide: items = [(no, chapter name, start page)]. Start page only, never a range."""
    s = prs.slides.add_slide(BLANK); N[0] += 1
    txt(s, L, 0.55, 9, 0.25, 'CONTENTS', size=11, bold=True, color=C['blue'])
    txt(s, L, 0.85, CW, 0.67, '목차', size=32, bold=True, color=C['ink'])
    for i, (no, name, page) in enumerate(items):
        y = 2.25 + i * 0.85
        txt(s, L, y, 0.97, 0.53, no, size=24, bold=True, color=C['blue'], anchor=MSO_ANCHOR.MIDDLE)
        txt(s, L + 1.26, y, 8.82, 0.53, name, size=24, bold=True, color=C['ink'], anchor=MSO_ANCHOR.MIDDLE)
        txt(s, SW - L - 0.92, y, 0.92, 0.53, f'{page:02d}', size=20, color=C['muted'], anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.RIGHT)
    txt(s, L, 7.0, 6, 0.22, FIRM['firm_name'], size=9.5, bold=True, color=C['light'])
    txt(s, SW - L - 1, 7.0, 1, 0.22, f'{N[0]:02d}', size=9.5, color=C['light'], align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = notes
    return s


def team_slide(label, headline, sub, people=None, notes=''):
    """Two-card team slide: photo, title, name, career, representative work. people defaults to FIRM['people']."""
    s = slide(label, headline, sub, notes)
    people = (people or FIRM.get('people') or DEFAULT_PEOPLE)[:2]
    tw2 = (CW - 0.3) / 2
    for i, p in enumerate(people):
        x = L + i * (tw2 + 0.3)
        box(s, x, 2.3, tw2, 4.45, fill=C['surface'])
        pic = s.shapes.add_picture(asset_path(p.get('photo') or DEFAULT_PEOPLE[i]['photo']),
                                   Inches(x + 0.3), Inches(2.6), Inches(2.3), Inches(3.45))
        if p.get('crop'):
            pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = p['crop']
        tx = x + 2.9; tw_ = tw2 - 3.15
        txt(s, tx, 2.6, tw_, 0.3, p.get('title', ''), size=11, bold=True, color=C['blue'])
        txt(s, tx, 2.9, tw_, 0.5, [[(p.get('name', '[이름]'), {'size': 22, 'bold': True, 'color': C['ink']}),
                                    ('  ' + p.get('role', ''), {'size': 13, 'color': C['muted']})]])
        txt(s, tx, 3.42, tw_, 0.3, p.get('name_en', ''), size=11, color=C['light'])
        line(s, tx, 3.85, tw_, C['line'])
        txt(s, tx, 3.98, tw_, 0.9, [_with_han(c) for c in p.get('career', [])], size=13, color=C['text'], spacing=1.2, after=2)
        txt(s, tx, 4.95, tw_, 0.3, '대표 수행업무', size=12, bold=True, color=C['blue'])
        txt(s, tx, 5.28, tw_, 1.3, ['· ' + w_ for w_ in p.get('work', [])], size=12.5, color=C['text'], spacing=1.2, after=4)
    return s


def next_step(label, headline, sub, steps, info=None, notes=''):
    """Process cards (3~4 steps) + optional '처음 문의 때 알려주실 정보' box + contact box from FIRM."""
    s = slide(label, headline, sub, notes)
    n = len(steps); fw = (CW - (n - 1) * 0.3) / n
    for i, (nm, d) in enumerate(steps):
        x = L + i * (fw + 0.3)
        box(s, x, 2.3, fw, 2.3, fill=C['surface'])
        txt(s, x + 0.3, 2.5, 1, 0.3, f'0{i+1}', size=13, bold=True, color=C['blue'])
        txt(s, x + 0.3, 2.82, fw - 0.5, 0.45, nm, size=17 if n > 3 else 20, bold=True, color=C['ink'])
        txt(s, x + 0.3, 3.35, fw - 0.55, 1.2, d, size=13 if n > 3 else 14, color=C['text'], spacing=1.3)
        if i < n - 1: arrow(s, x + fw + 0.04, 3.45, x + fw + 0.26)
    cx_ = L + 7.7 if info else L
    if info:
        box(s, L, 4.85, 7.4, 1.9, fill=C['pale'])
        txt(s, L + 0.35, 5.0, 6.8, 0.3, '처음 문의하실 때 알려주실 정보', size=13, bold=True, color=C['blue'])
        txt(s, L + 0.35, 5.35, 6.8, 1.35, ['· ' + t for t in info], size=13, color=C['ink'], spacing=1.15, after=2)
    cw_ = SW - L - cx_
    box(s, cx_, 4.85, cw_, 1.9, fill=C['dark'])
    for j, (k, v) in enumerate([('웹사이트', FIRM['website']), ('이메일', FIRM['email'])]):
        y = 5.1 + j * 0.75
        txt(s, cx_ + 0.35, y, 1.2, 0.5, k, size=12, bold=True, color=C['sky'], anchor=MSO_ANCHOR.MIDDLE)
        txt(s, cx_ + 1.4, y, cw_ - 1.6, 0.5, v, size=15 if info else 20, bold=True, color=C['white'], anchor=MSO_ANCHOR.MIDDLE)
    return s


def firm_profile(no='05', chapter=None):
    """Divider + 4 profile slides (개요, 매출 추이, 업무 구성, 사무소) from FIRM['profile'].
    Every figure must come from a dated source the firm has checked (references/firm-facts.template.md)."""
    chapter = chapter or f"{FIRM['firm_name']} 소개"
    pf = dict(DEFAULT_PROFILE); pf.update(FIRM.get('profile') or {})
    src = pf['source']
    divider(no, chapter, [])

    # 1 개요 ---------------------------------------------------------------------
    s = slide('AT A GLANCE', f'{chapter}(1/4) - 법인 개요', f"{pf['as_of']} 법인의 규모와 주요 업무입니다.", src)
    gw_, gh_ = 3.05, 2.05
    for i, (n, u, c) in enumerate(pf['stats'][:4]):
        x = L + (i % 2) * (gw_ + 0.2); y = 2.3 + (i // 2) * (gh_ + 0.2)
        box(s, x, y, gw_, gh_, fill=C['surface'])
        txt(s, x + 0.3, y + 0.3, gw_ - 0.5, 0.7, [[(n, {'size': 30, 'bold': True, 'color': C['ink']}), (' ' + u, {'size': 15, 'bold': True, 'color': C['muted']})]],
            anchor=MSO_ANCHOR.BOTTOM)
        txt(s, x + 0.3, y + 1.15, gw_ - 0.5, 0.7, c, size=13, color=C['text'], spacing=1.25)
    info = pf['info']
    ix = L + 2 * gw_ + 0.2 + 0.5; iw_ = SW - L - ix
    rh = (2 * gh_ + 0.2) / max(1, len(info))
    for i, (k, v) in enumerate(info):
        y = 2.3 + i * rh
        line(s, ix, y, iw_, C['ink'] if i == 0 else C['line'], 1.0 if i == 0 else 0.75)
        txt(s, ix, y, 1.3, rh, k, size=13, bold=True, color=C['ink'], anchor=MSO_ANCHOR.MIDDLE)
        txt(s, ix + 1.35, y, iw_ - 1.35, rh, v, size=13, color=C['text'], anchor=MSO_ANCHOR.MIDDLE)
    line(s, ix, 2.3 + len(info) * rh, iw_, C['line'])

    # 2 매출 추이 ------------------------------------------------------------------
    rv = pf['revenue']
    s = slide('GROWTH', f'{chapter}(2/4) - 매출 추이', f"{rv['labels'][0]}부터 {rv['labels'][-1]}까지의 매출 변화입니다.", src)
    txt(s, L, 2.0, CW, 0.25, f"(단위: {rv.get('unit', '억원')})", size=10.5, color=C['muted'], align=PP_ALIGN.RIGHT)
    cd = CategoryChartData(); cd.categories = rv['labels']; cd.add_series('매출', rv['values'])
    ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(L - 0.1), Inches(2.3), Inches(CW + 0.2), Inches(4.35), cd).chart
    chart_font(ch); ch.has_legend = False
    pl = ch.plots[0]; pl.gap_width = 45
    ser = pl.series[0]; ser.format.fill.solid(); ser.format.fill.fore_color.rgb = rgb(C['grey'])
    p = ser.points[len(rv['values']) - 1]; p.format.fill.solid(); p.format.fill.fore_color.rgb = rgb(C['blue'])
    pl.has_data_labels = True; dl = pl.data_labels
    dl.number_format = '#,##0.0'; dl.number_format_is_linked = False; dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size = Pt(11); dl.font.color.rgb = rgb(C['text'])
    ch.value_axis.visible = False; ch.value_axis.has_major_gridlines = False
    ch.value_axis.maximum_scale = max(rv['values']) * 1.15; ch.value_axis.minimum_scale = 0
    ch.category_axis.tick_labels.font.size = Pt(11); ch.category_axis.format.line.color.rgb = rgb(C['line'])

    # 3 업무 구성 ------------------------------------------------------------------
    mix = pf['mix']; total = sum(v for _, v in mix) or 1
    s = slide('SERVICE MIX', f'{chapter}(3/4) - 업무별 매출 구성', '업무 영역별 매출 비중입니다.', src)
    cd = CategoryChartData(); cd.categories = [k for k, _ in mix]; cd.add_series('구성', [v for _, v in mix])
    gf = s.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, Inches(L - 0.1), Inches(2.3), Inches(4.3), Inches(4.3), cd)
    ch = gf.chart; chart_font(ch); ch.has_legend = False
    pl = ch.plots[0]
    hole = pl._element.find(qn('c:holeSize'))
    if hole is None: hole = etree.SubElement(pl._element, qn('c:holeSize'))
    hole.set('val', '62')
    cols = [C['blue'], C['sky'], C['grey'], C['blue2'], C['line']]
    for i in range(len(mix)):
        pt = pl.series[0].points[i]; pt.format.fill.solid(); pt.format.fill.fore_color.rgb = rgb(cols[i % len(cols)])
        pt.format.line.color.rgb = rgb(C['white']); pt.format.line.width = Pt(1.5)
    rx = 5.55; rw = SW - L - rx
    for i, (k, v) in enumerate(mix):
        y = 2.65 + i * 1.1
        line(s, rx, y, rw, C['line'])
        box(s, rx, y + 0.28, 0.16, 0.16, fill=cols[i % len(cols)], shape=MSO_SHAPE.OVAL)
        txt(s, rx + 0.3, y + 0.18, 3.5, 0.35, k, size=17, bold=True, color=C['ink'])
        txt(s, rx + 4.0, y + 0.18, rw - 4.0, 0.35, f'{v / total * 100:.1f}%', size=17, bold=True, color=C['blue'], align=PP_ALIGN.RIGHT)
    line(s, rx, 2.65 + len(mix) * 1.1, rw, C['line'])

    # 4 사무소 ---------------------------------------------------------------------
    offices = pf['offices'][:4]
    s = slide('NETWORK', f'{chapter}(4/4) - 사무소 현황', '지역별 사무소 구성입니다.', src)
    rw = (CW - 0.2 * (len(offices) - 1)) / max(1, len(offices))
    for i, (nm, lst) in enumerate(offices):
        x = L + i * (rw + 0.2)
        txt(s, x, 2.3, rw, 0.3, nm, size=14, bold=True, color=C['ink'])
        txt(s, x, 2.62, rw, 0.6, [[(str(len(lst)), {'size': 30, 'bold': True, 'color': C['blue']}), (' 개소', {'size': 14, 'bold': True, 'color': C['muted']})]])
        line(s, x, 3.35, rw, C['ink'], 1.0)
        txt(s, x, 3.5, rw, 3.2, lst, size=12.5, color=C['text'], spacing=1.15, after=5)


def thank_you():
    s = prs.slides.add_slide(BLANK); N[0] += 1
    dark_bg(s)
    logo(s, L, 2.2, 0.9)
    txt(s, L, 3.35, 11, 1.0, '감사합니다.', size=48, bold=True, color=C['white'])
    txt(s, L, 4.35, 11, 0.5, 'Thank you', size=22, color=C['sky'])
    line(s, L, 5.55, CW, C['dline'])
    txt(s, L, 5.8, 3.6, 0.35, FIRM['firm_name'], size=14, bold=True, color=C['white'], anchor=MSO_ANCHOR.MIDDLE)
    txt(s, 4.6, 5.8, 3.6, 0.35, FIRM['website'], size=14, color=C['onDark'], anchor=MSO_ANCHOR.MIDDLE)
    txt(s, 8.3, 5.8, 4.28, 0.35, FIRM['email'], size=14, color=C['onDark'], anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = ''
    return s
