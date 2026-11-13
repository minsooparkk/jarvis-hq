# -*- coding: utf-8 -*-
"""Proposal/report deck builder library (Korean, 16:9, Pretendard).

Firm-specific values (name, logo, contacts, people, palette) come from a JSON config:
  1) env PROPOSAL_DECK_FIRM=/path/firm.json, else 2) <skill>/assets/firm.json, else
  3) built-in placeholders ('○○회계법인'). Copy assets/firm.example.json to assets/firm.json and edit it.

Usage (one deck per process):
    import sys, os
    sys.path.insert(0, os.path.join(<skill_dir>, 'scripts'))
    from deck_lib import *
    from sections import *
    cover(...); divider(...); s = slide(...); ...; save(path)

Coordinates are inches on a 13.333 x 7.5 slide. Body area: x=L..L+CW, y=2.3..6.75.
Footer (brand + page number) is added by slide(); divider() adds page number only.
"""
import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.oxml.ns import qn
from lxml import etree

import json, os
ASSET = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets'))
SKILL_DIR = os.path.dirname(ASSET)
PLACEHOLDER_FIRM = {
    "firm_name": "○○회계법인", "firm_name_en": "OO ACCOUNTING", "logo": "assets/logo_placeholder.png",
    "website": "www.example.com", "email": "contact@example.com",
    "people": [], "palette": {},
}


def load_firm():
    """Firm config: env PROPOSAL_DECK_FIRM, else assets/firm.json, else placeholders. Never prompts."""
    path = os.environ.get('PROPOSAL_DECK_FIRM') or os.path.join(ASSET, 'firm.json')
    cfg = dict(PLACEHOLDER_FIRM)
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as fh:
                cfg.update(json.load(fh))
        except (OSError, ValueError) as e:
            sys.stderr.write(f"firm config '{path}' could not be read ({e}); using placeholders\n")
    elif os.environ.get('PROPOSAL_DECK_FIRM'):
        sys.stderr.write(f"PROPOSAL_DECK_FIRM='{path}' not found; using placeholders\n")
    cfg['_source'] = path if os.path.isfile(path) else 'placeholders'
    return cfg


FIRM = load_firm()


def asset_path(rel):
    """Resolve a config path relative to the skill folder (or absolute)."""
    return rel if os.path.isabs(rel) else os.path.join(SKILL_DIR, rel)


FONT = "Pretendard"
C = dict(dark="062456", ink="0F1B2D", text="394656", muted="5F6B7A", light="8A94A3",
         blue="176098", blue2="2B88B6", pale="E8F1F8", surface="F4F7FA", line="DFE6EE",
         white="FFFFFF", grey="C7D5E3", sky="9CC3E0", onDark="C3D3E4", dline="1F4172")
C.update({k: v for k, v in FIRM.get("palette", {}).items() if k in C})
def rgb(h): return RGBColor.from_string(h)

prs = Presentation()
prs.slide_width = Inches(13.333333); prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
SW = 13.333333
L = 0.75          # left margin
CW = SW - 2 * L   # content width

# theme fonts
for rel in prs.slide_masters[0].part.rels.values():
    if rel.reltype.endswith('/theme'):
        tp = rel.target_part
        root = etree.fromstring(tp.blob)
        ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
        for tag in ('a:majorFont', 'a:minorFont'):
            f = root.find('.//' + tag, ns)
            f.find('a:latin', ns).set('typeface', FONT); f.find('a:ea', ns).set('typeface', FONT)
            for fnt in f.findall('a:font', ns):
                if fnt.get('script') == 'Hang': fnt.set('typeface', FONT)
        tp._blob = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)

def font_run(run, size, bold, color, face=None):
    face = face or FONT
    f = run.font; f.name = face; f.size = Pt(size); f.bold = bold; f.color.rgb = rgb(color)
    rPr = run._r.get_or_add_rPr()
    # Korean language tag: PowerPoint then wraps Hangul at word boundaries instead of mid-word ('검/토').
    # (eaLnBrk alone has no effect in PowerPoint for Mac; verified in PowerPoint for Mac.)
    rPr.set('lang', 'ko-KR'); rPr.set('altLang', 'en-US')
    for t in ('a:ea', 'a:cs'):
        el = rPr.find(qn(t))
        if el is None: el = etree.SubElement(rPr, qn(t))
        el.set('typeface', face)

def txt(s, x, y, w, h, paras, size=15, bold=False, color=None, align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.TOP, spacing=1.15, after=0):
    color = color or C['text']
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True; tf.auto_size = None
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if isinstance(paras, str): paras = [paras]
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align; para.line_spacing = spacing; para.space_after = Pt(after)
        for t, o in (p if isinstance(p, list) else [(p, {})]):
            r = para.add_run(); r.text = t
            font_run(r, o.get('size', size), o.get('bold', bold), o.get('color', color), o.get('font'))
    return tb

def box(s, x, y, w, h, fill=None, line=None, shape=MSO_SHAPE.RECTANGLE, lw=0.75):
    b = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill: b.fill.solid(); b.fill.fore_color.rgb = rgb(fill)
    else: b.fill.background()
    if line: b.line.color.rgb = rgb(line); b.line.width = Pt(lw)
    else: b.line.fill.background()
    b.shadow.inherit = False
    return b

def line(s, x, y, w, color, weight=0.75, vertical=False):
    x2, y2 = (x, y + w) if vertical else (x + w, y)
    ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y), Inches(x2), Inches(y2))
    ln.line.color.rgb = rgb(color); ln.line.width = Pt(weight)
    return ln

def arrow(s, x1, y, x2, color=None):
    ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y), Inches(x2), Inches(y))
    ln.line.color.rgb = rgb(color or C['blue2']); ln.line.width = Pt(1.5)
    t = etree.SubElement(ln.line._get_or_add_ln(), qn('a:tailEnd')); t.set('type', 'triangle')

def logo(s, x, y, d):
    s.shapes.add_picture(asset_path(FIRM['logo']), Inches(x), Inches(y), Inches(d), Inches(d))

def dark_bg(s):
    bg = box(s, 0, 0, SW, 7.5, fill=C['dark'])
    bg.fill.gradient(); bg.fill.gradient_angle = 135
    st = bg.fill.gradient_stops
    st[0].color.rgb = rgb('041A40'); st[0].position = 0; st[1].color.rgb = rgb('0B3A73'); st[1].position = 1.0

N = [0]
def divider(no, title, items, notes=''):
    s = prs.slides.add_slide(BLANK); N[0] += 1
    dark_bg(s)
    logo(s, L, 0.62, 0.38)
    txt(s, L + 0.5, 0.62, 4, 0.38, FIRM['firm_name'], size=14, bold=True, color=C['white'], anchor=MSO_ANCHOR.MIDDLE)
    txt(s, L, 2.4, 3, 1.1, no, size=54, bold=True, color=C['blue2'])
    txt(s, L, 3.55, 10, 0.8, title, size=36, bold=True, color=C['white'])
    line(s, L, 4.6, 5.2, C['dline'])
    txt(s, L, 4.85, 11, 1.4, ['  ·  '.join(items[:3]), '  ·  '.join(items[3:])] if len(items) > 4 else '  ·  '.join(items), size=15, color=C['onDark'], spacing=1.4)
    txt(s, SW - L - 1, 7.0, 1, 0.22, f'{N[0]:02d}', size=9.5, color='7F97B8', align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = notes or f'간지: {no} {title}'
    return s

def slide(label, headline, sub=None, notes='', dark=False):
    s = prs.slides.add_slide(BLANK); N[0] += 1
    if dark: dark_bg(s)
    txt(s, L, 0.55, 9, 0.25, label, size=11, bold=True, color=C['sky'] if dark else C['blue'])
    txt(s, L, 0.85, CW, 0.6, headline, size=26, bold=True, color=C['white'] if dark else C['ink'])
    if sub:
        txt(s, L, 1.52, CW, 0.35, sub, size=15, color=C['onDark'] if dark else C['muted'])
    fc = '7F97B8' if dark else C['light']
    txt(s, L, 7.0, 6, 0.22, FIRM['firm_name'], size=9.5, bold=True, color=fc)
    txt(s, SW - L - 1, 7.0, 1, 0.22, f'{N[0]:02d}', size=9.5, color=fc, align=PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = notes
    return s

def chart_font(ch, size=11):
    ch.font.name = FONT; ch.font.size = Pt(size); ch.font.color.rgb = rgb(C['muted'])
    txPr = ch._chartSpace.find(qn('c:txPr'))
    if txPr is not None:
        for rpr in txPr.iter(qn('a:defRPr')):
            for t in ('a:ea', 'a:cs'):
                el = rpr.find(qn(t))
                if el is None: el = etree.SubElement(rpr, qn(t))
                el.set('typeface', FONT)

def big(s, x, y, w, num, unit, cap, dark=False, numc=None, size=40):
    txt(s, x, y, w, 0.75, [[(num, {'size': size, 'bold': True, 'color': numc or (C['white'] if dark else C['ink'])}),
                            (' ' + unit, {'size': 16, 'bold': True, 'color': C['onDark'] if dark else C['muted']})]],
        anchor=MSO_ANCHOR.BOTTOM)
    txt(s, x, y + 0.85, w, 0.9, cap, size=14, color=C['onDark'] if dark else C['text'], spacing=1.25)



HAN = [('前', {'font': 'Malgun Gothic'})]   # Pretendard has no CJK ideographs; render 前 with Malgun Gothic


def cell(c, text, size, bold, color, fill):
    """Fill one native table cell (python-pptx _Cell)."""
    c.fill.solid(); c.fill.fore_color.rgb = rgb(fill)
    c.margin_left = c.margin_right = Inches(0.2); c.margin_top = c.margin_bottom = Inches(0.06)
    c.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = c.text_frame.paragraphs[0]; p.line_spacing = 1.15
    r = p.add_run(); r.text = text; font_run(r, size, bold, color)


def table(s, x, y, widths, header, rows, row_h=0.8, head_h=0.5, size=13.5, style=None):
    """Native table: dark header row, zebra body rows. style(i, j, value) -> (bold, color) optional."""
    tb = s.shapes.add_table(len(rows) + 1, len(widths), Inches(x), Inches(y), Inches(sum(widths)), Inches(head_h + row_h * len(rows))).table
    for j, wv in enumerate(widths): tb.columns[j].width = Inches(wv)
    for j, h in enumerate(header): cell(tb.cell(0, j), h, size - 0.5, True, C['white'], C['dark'])
    tb.rows[0].height = Inches(head_h)
    for i, row in enumerate(rows, 1):
        tb.rows[i].height = Inches(row_h)
        for j, v in enumerate(row):
            bold, color = style(i, j, v) if style else (j == 0, C['ink'] if j == 0 else C['text'])
            cell(tb.cell(i, j), v, size, bold, color, C['white'] if i % 2 else C['surface'])
    tb._tbl.tblPr.set('firstRow', '0'); tb._tbl.tblPr.set('bandRow', '0')
    return tb


def save(path, title=None):
    if title: prs.core_properties.title = title
    prs.save(path)
    print('saved', len(prs.slides), 'slides ->', path)
