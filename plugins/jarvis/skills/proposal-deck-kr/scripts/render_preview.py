# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0", "pillow"]
# ///
# -*- coding: utf-8 -*-
"""Approximate PPTX preview renderer for visual QA when PowerPoint cannot be automated.

uv run scripts/render_preview.py deck.pptx OUT_DIR [--px 120] [--sheets] [--pdf out.pdf]

Limits: wraps Korean by spaces (word units). PowerPoint without eaLnBrk=0 breaks Hangul mid-word,
which this preview does NOT show — use powerpoint_check.py for that. Not a PowerPoint render.
Output: 'sNN overflow' / 'sNN out-of-bounds' lines (or 'no text overflow detected') on stdout,
font warnings on stderr. Exit 0 always after rendering; 2 if the deck cannot be opened.

- Draws rectangles, ovals, lines/arrows, pictures (with crop), native tables, simple
  column/bar/doughnut charts and wrapped text with real Pretendard metrics.
- Prints 'sNN overflow' lines when a text frame's wrapped height exceeds its box.
- --sheets writes 2x2 contact sheets (sheet1.png ...). --pdf bundles page images into an
  image-only PDF (text not selectable). Charts are simplified; not a PowerPoint render.
Fonts: Pretendard-Regular/Bold (.otf/.ttf) are searched in $PRETENDARD_DIR, this folder,
~/Library/Fonts, /Library/Fonts, %LOCALAPPDATA%/Microsoft/Windows/Fonts, C:/Windows/Fonts.
CJK ideographs (e.g. 前) fall back to Malgun Gothic / Apple SD Gothic Neo when available.
"""
import sys, os, math
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.dml import MSO_FILL
from pptx.enum.chart import XL_CHART_TYPE
from PIL import Image, ImageDraw, ImageFont

import argparse, glob
ap = argparse.ArgumentParser(
    description='Approximate preview (PNG per slide) + text overflow / out-of-bounds report for a proposal/report deck.',
    epilog='example: uv run scripts/render_preview.py out/deck.pptx out/preview --sheets\n'
           'stdout lists "sNN overflow ..." per problem, or "no text overflow detected".',
    formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('pptx', help='input .pptx')
ap.add_argument('outdir', help='folder for sNN.png (created if missing; existing PNGs are overwritten)')
ap.add_argument('--px', type=float, default=120.0, help='pixels per inch (default 120; 240 for PDF)')
ap.add_argument('--sheets', action='store_true', help='also write 2x2 contact sheets sheetN.png')
ap.add_argument('--pdf', help='also bundle the PNGs into an image-only PDF at this path')
args = ap.parse_args()
src, outdir = args.pptx, args.outdir
if not os.path.isfile(src) or not src.lower().endswith('.pptx'):
    sys.stderr.write(f"input '{src}' not found or not a .pptx file; pass the deck path first, then the output folder\n")
    sys.exit(2)
os.makedirs(outdir, exist_ok=True)
PX = args.px


def _find(names):
    dirs = [os.environ.get('PRETENDARD_DIR', ''), os.path.dirname(os.path.abspath(__file__)),
            os.path.expanduser('~/Library/Fonts'), '/Library/Fonts', '/System/Library/Fonts',
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts'), r'C:\Windows\Fonts',
            '/usr/share/fonts', os.path.expanduser('~/.fonts')]
    for d in dirs:
        if not d or not os.path.isdir(d): continue
        for n in names:
            hit = glob.glob(os.path.join(d, '**', n), recursive=True)
            if hit: return hit[0]
    return None
EMU = 914400.0
FR = _find(['Pretendard-Regular.otf', 'Pretendard-Regular.ttf']) or _find(['malgun.ttf', 'AppleSDGothicNeo.ttc'])
FB = _find(['Pretendard-Bold.otf', 'Pretendard-Bold.ttf']) or _find(['malgunbd.ttf', 'AppleSDGothicNeo.ttc']) or FR
HR = _find(['malgun.ttf', 'AppleSDGothicNeo.ttc', 'NotoSansCJK-Regular.ttc']) or FR
HB = _find(['malgunbd.ttf', 'AppleSDGothicNeo.ttc', 'NotoSansCJK-Bold.ttc']) or HR
if not FR:
    sys.stderr.write('no usable font found (Pretendard / Malgun Gothic / Apple SD Gothic Neo); set PRETENDARD_DIR to the folder with Pretendard-Regular.otf\n')
    sys.exit(2)
if 'Pretendard' not in os.path.basename(FR):
    sys.stderr.write('WARNING: Pretendard not found; preview uses a fallback font and wrapping may differ\n')
_fc = {}
def font(pt, bold):
    k = (round(pt * 2) / 2, bold)
    if k not in _fc: _fc[k] = ImageFont.truetype(FB if bold else FR, max(6, int(round(pt * PX / 72))))
    return _fc[k]
def e(v): return v / EMU * PX
def hexrgb(c): return '#' + str(c)
issues = []

def fill_color(sh):
    try:
        f = sh.fill
        if f.type == MSO_FILL.SOLID: return hexrgb(f.fore_color.rgb)
        if f.type == MSO_FILL.GRADIENT: return hexrgb(f.gradient_stops[0].color.rgb)
    except Exception: pass
    return None

def line_color(sh):
    try:
        if sh.line.fill.type == MSO_FILL.SOLID: return hexrgb(sh.line.color.rgb), max(1, int(sh.line.width.pt * PX / 72))
    except Exception: pass
    return None, 0

def draw_text(d, tf, x, y, w, h, sid, name, default_color='#000000'):
    ml, mr, mt, mb = [e(v) if v is not None else 0 for v in (tf.margin_left, tf.margin_right, tf.margin_top, tf.margin_bottom)]
    ix, iy, iw, ih = x + ml, y + mt, w - ml - mr, h - mt - mb
    lines = []  # (items[(ch,font,color)], height, align)
    for p in tf.paragraphs:
        runs = p.runs
        size = max([r.font.size.pt for r in runs if r.font.size] or [18])
        ls = p.line_spacing if isinstance(p.line_spacing, float) else 1.0
        lh = size * PX / 72 * 1.2 * ls
        items = []
        for r in runs:
            sz = r.font.size.pt if r.font.size else size
            col = hexrgb(r.font.color.rgb) if (r.font.color and r.font.color.type is not None) else default_color
            f = font(sz, bool(r.font.bold))
            for ch in r.text:
                if 0x4E00 <= ord(ch) <= 0x9FFF: items.append((ch, ImageFont.truetype(HB if r.font.bold else HR, max(6, int(round(sz * PX / 72)))), col))
                else: items.append((ch, f, col))
        # wrap by words
        cur, curw, out = [], 0.0, []
        i = 0
        tokens, tok = [], []
        for it in items:
            tok.append(it)
            if it[0] == ' ': tokens.append(tok); tok = []
        if tok: tokens.append(tok)
        for tk in tokens:
            tw = sum(it[1].getlength(it[0]) for it in tk)
            if curw + tw > iw + 0.5 and cur:
                out.append(cur); cur, curw = [], 0.0
                if tw > iw:  # break long token by chars
                    for it in tk:
                        cw_ = it[1].getlength(it[0])
                        if curw + cw_ > iw and cur: out.append(cur); cur, curw = [], 0.0
                        cur.append(it); curw += cw_
                    continue
            cur += tk; curw += tw
        out.append(cur)
        for ln in out: lines.append((ln, lh, p.alignment))
        sa = p.space_after.pt * PX / 72 if p.space_after is not None else 0
        if lines: lines[-1] = (lines[-1][0], lines[-1][1] + sa, lines[-1][2])
    total = sum(l[1] for l in lines)
    if total > ih + 4 and ''.join(it[0] for l in lines for it in l[0]).strip():
        issues.append(f's{sid} overflow {total:.0f}>{ih:.0f}px "{"".join(it[0] for it in lines[0][0])[:28]}"')
    anc = tf.vertical_anchor
    cy = iy + ((ih - total) / 2 if anc == MSO_ANCHOR.MIDDLE else (ih - total) if anc == MSO_ANCHOR.BOTTOM else 0)
    for ln, lh, al in lines:
        lw = sum(it[1].getlength(it[0]) for it in ln)
        cx = ix + ((iw - lw) / 2 if al == PP_ALIGN.CENTER else (iw - lw) if al == PP_ALIGN.RIGHT else 0)
        base = cy + lh * 0.8
        for ch, f, col in ln:
            d.text((cx, base), ch, font=f, fill=col, anchor='ls')
            cx += f.getlength(ch)
        cy += lh

def draw_chart(d, gf, x, y, w, h):
    ch = gf.chart
    ct = ch.chart_type
    plot = ch.plots[0]
    cats = list(plot.categories)
    sers = list(plot.series)
    f = font(10.5, False)
    if ct == XL_CHART_TYPE.DOUGHNUT:
        vals = list(sers[0].values); tot = sum(vals); a = -90
        cx, cy, r = x + w / 2, y + h / 2, min(w, h) / 2 - 20
        cols = []
        for i in range(len(vals)):
            try: cols.append(hexrgb(sers[0].points[i].format.fill.fore_color.rgb))
            except Exception: cols.append('#999999')
        for v, c in zip(vals, cols):
            sweep = 360 * v / tot
            d.pieslice([cx - r, cy - r, cx + r, cy + r], a, a + sweep, fill=c, outline='#FFFFFF', width=3)
            a += sweep
        r2 = r * 0.62; d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill='#FFFFFF')
        return
    horiz = ct == XL_CHART_TYPE.BAR_CLUSTERED
    stacked = ct == XL_CHART_TYPE.COLUMN_STACKED
    vmax = ch.value_axis.maximum_scale or max(max(s.values) for s in sers) * 1.15
    n = len(cats)
    pad = (60 if horiz else 30) * PX / 120
    if horiz:
        slot = (h - 20) / n
        for i, c in enumerate(cats):
            yy = y + 10 + (n - 1 - i) * slot
            v = sers[0].values[i]; bw = (w - pad - 90) * v / vmax
            try: col = hexrgb(sers[0].points[i].format.fill.fore_color.rgb)
            except Exception: col = '#C9D3E3'
            d.rectangle([x + pad, yy + slot * 0.15, x + pad + bw, yy + slot * 0.85], fill=col)
            d.line([x + pad, y + 10, x + pad, y + h - 10], fill='#DFE6EE', width=max(1, int(PX / 120)))
            d.text((x + pad - 8, yy + slot / 2), str(c), font=font(12, False), fill='#626D7D', anchor='rm')
            d.text((x + pad + bw + 6, yy + slot / 2), f'{v:,.1f}', font=f, fill='#3B4658', anchor='lm')
    else:
        slot = (w - 20) / n; base = y + h - 30 * PX / 120
        d.line([x + 10, base, x + w - 10, base], fill='#DFE6EE', width=max(1, int(PX / 120)))
        for i, c in enumerate(cats):
            xx = x + 10 + i * slot; acc = 0
            for s in sers:
                v = s.values[i]; bh = (h - 70) * v / vmax
                try: col = hexrgb(s.points[i].format.fill.fore_color.rgb)
                except Exception: col = hexrgb(s.format.fill.fore_color.rgb) if s.format.fill.type == MSO_FILL.SOLID else '#C9D3E3'
                top = base - acc - bh
                d.rectangle([xx + slot * 0.2, top, xx + slot * 0.8, base - acc], fill=col)
                if stacked: d.text((xx + slot / 2, top + bh / 2), f'{v:,.1f}', font=f, fill='#101622', anchor='mm')
                acc += bh if stacked else 0
                if not stacked: d.text((xx + slot / 2, top - 4), f'{v:,.1f}', font=f, fill='#3B4658', anchor='ms')
            d.text((xx + slot / 2, base + 6), str(c), font=font(11, False), fill='#626D7D', anchor='mt')

try:
    prs = Presentation(src)
except Exception as ex:  # noqa: BLE001
    sys.stderr.write(f"cannot open '{src}' as PPTX: {ex.__class__.__name__}: {ex}\n")
    sys.exit(2)
W, H =int(e(prs.slide_width)), int(e(prs.slide_height))
for sid, s in enumerate(prs.slides, 1):
    img = Image.new('RGB', (W, H), '#FFFFFF'); d = ImageDraw.Draw(img)
    for sh in s.shapes:
        x, y, w, h = e(sh.left), e(sh.top), e(sh.width), e(sh.height)
        if x < -1 or y < -1 or x + w > W + 2 or y + h > H + 2: issues.append(f's{sid} out-of-bounds {sh.name}')
        if sh.shape_type == MSO_SHAPE_TYPE.LINE or sh.shape_type == MSO_SHAPE_TYPE.CONNECTOR if hasattr(MSO_SHAPE_TYPE, 'CONNECTOR') else False:
            pass
        tag = sh._element.tag.split('}')[1]
        if tag == 'cxnSp':
            col, lw = line_color(sh)
            d.line([e(sh.begin_x), e(sh.begin_y), e(sh.end_x), e(sh.end_y)], fill=col or '#000', width=lw or 1)
            continue
        if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
            import io
            im = Image.open(io.BytesIO(sh.image.blob)).convert('RGBA'); iw0, ih0 = im.size
            im = im.crop((int(iw0 * sh.crop_left), int(ih0 * sh.crop_top), int(iw0 * (1 - sh.crop_right)), int(ih0 * (1 - sh.crop_bottom)))).resize((int(w), int(h)))
            img.paste(im, (int(x), int(y)), im); continue
        if sh.has_chart:
            draw_chart(d, sh, x, y, w, h); continue
        if sh.has_table:
            tb = sh.table; cy = y
            for ri, row in enumerate(tb.rows):
                rh = e(row.height); cx = x
                for ci, col in enumerate(tb.columns):
                    cw_ = e(col.width); c = tb.cell(ri, ci)
                    fc = hexrgb(c.fill.fore_color.rgb) if c.fill.type == MSO_FILL.SOLID else '#FFFFFF'
                    d.rectangle([cx, cy, cx + cw_, cy + rh], fill=fc, outline='#E1E6EE')
                    draw_text(d, c.text_frame, cx + e(c.margin_left), cy + e(c.margin_top), cw_ - e(c.margin_left) - e(c.margin_right), rh - e(c.margin_top) - e(c.margin_bottom), sid, 'cell')
                    cx += cw_
                cy += rh
            continue
        if tag == 'sp':
            fc = fill_color(sh); lc, lw = line_color(sh)
            try: ast = sh.auto_shape_type
            except Exception: ast = None
            if fc or lc:
                if ast == MSO_SHAPE.OVAL: d.ellipse([x, y, x + w, y + h], fill=fc, outline=lc, width=lw)
                elif ast == MSO_SHAPE.ROUNDED_RECTANGLE: d.rounded_rectangle([x, y, x + w, y + h], radius=min(w, h) / 2, fill=fc, outline=lc, width=lw)
                elif ast is None and fc:  # freeform (logo triangle)
                    d.polygon([(x + w * .5, y), (x + w, y + h), (x + w * .6, y + h), (x + w * .5, y + h * .55), (x + w * .4, y + h), (x, y + h)], fill=fc)
                else: d.rectangle([x, y, x + w, y + h], fill=fc, outline=lc, width=lw)
            if sh.has_text_frame and sh.text_frame.text.strip():
                draw_text(d, sh.text_frame, x, y, w, h, sid, sh.name)
    img.save(os.path.join(outdir, f's{sid:02d}.png'))
print('\n'.join(issues) if issues else 'no text overflow detected')

pages = sorted(glob.glob(os.path.join(outdir, 's[0-9][0-9].png')))
if args.sheets:
    for k in range(0, len(pages), 4):
        ims = [Image.open(f) for f in pages[k:k + 4]]
        Wd, Ht = ims[0].size; sheet = Image.new('RGB', (Wd * 2 + 30, Ht * 2 + 30), '#888')
        for i, im in enumerate(ims): sheet.paste(im, ((i % 2) * (Wd + 30), (i // 2) * (Ht + 30)))
        sheet.resize((sheet.width // 2, sheet.height // 2)).save(os.path.join(outdir, f'sheet{k // 4 + 1}.png'))
if args.pdf:
    ims = [Image.open(f).convert('RGB') for f in pages]
    ims[0].save(args.pdf, 'PDF', resolution=PX, save_all=True, append_images=ims[1:], quality=92)
    print('pdf', args.pdf, len(ims), 'pages')



