"""Page assembly for the sample works: generated panel art + code-drawn borders, balloons, lettering and manpu; exact ground truth.

Everything that is text or a shape is drawn here (supersampled 2x), so the lettering is clean and `truth.json` is exact.
Inputs: a work script (`script.yaml`) and a directory of panel art `<page>_<panel>.png`. Outputs: pages/*.png, truth.json, truth/*_units.png.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from . import fonts

SS = 2
PAGE_W, PAGE_H = 850, 1200
SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ")
ROTATE = set("ー―〜～…（）(){}「」『』")
PUNCT = set("。、，．")


# ---------------------------------------------------------------- text
def _glyph(ch: str, role: str, fs: int, fill, stroke_w: int = 0, stroke_fill=None) -> Image.Image:
    f = fonts.load(role, fs)
    pad = fs // 2 + stroke_w
    im = Image.new("RGBA", (fs * 2 + 2 * pad, fs * 2 + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((im.width // 2, im.height // 2), ch, font=f, fill=fill, anchor="mm", stroke_width=stroke_w, stroke_fill=stroke_fill)
    return im


def text_layer(text: str, role: str, fs: int, vertical: bool, fill=(0, 0, 0, 255), stroke_w: int = 0, stroke_fill=(255, 255, 255, 255),
               line_gap: float = 1.18, step: float = 1.04, align: str = "mid") -> tuple[Image.Image, tuple[int, int]]:
    """Render a text block (columns split by newline) centred in an RGBA layer. Returns (layer, (w, h) of the text block)."""
    lines = text.split("\n")
    if vertical:
        ncol, nrow = len(lines), max(len(x) for x in lines)
        bw, bh = int(ncol * fs * line_gap), int(nrow * fs * step)
    else:
        nrow, ncol = len(lines), max(len(x) for x in lines)
        bw, bh = int(ncol * fs * step), int(nrow * fs * line_gap)
    m = fs + stroke_w * 2 + 4
    lay = Image.new("RGBA", (bw + 2 * m, bh + 2 * m), (0, 0, 0, 0))
    for li, line in enumerate(lines):
        for ci, ch in enumerate(line):
            if vertical:
                cx = m + bw - (li + 0.5) * fs * line_gap
                cy = m + (ci + 0.5) * fs * step + (0 if align == "top" else (nrow - len(line)) * fs * step / 2)
            else:
                cx = m + (ci + 0.5) * fs * step + (nrow and (ncol - len(line)) * fs * step / 2 if align == "mid" else 0)
                cy = m + (li + 0.5) * fs * line_gap
            g = _glyph(ch, role, fs, fill, stroke_w, stroke_fill)
            if vertical:
                if ch in ROTATE:
                    g = g.rotate(-90, expand=False, resample=Image.BICUBIC)
                if ch in PUNCT:
                    cx, cy = cx + fs * 0.52, cy - fs * 0.5
                elif ch in SMALL_KANA:
                    cx, cy = cx + fs * 0.1, cy - fs * 0.1
            lay.alpha_composite(g, (int(round(cx - g.width / 2)), int(round(cy - g.height / 2))))
    return lay, (bw, bh)


# ---------------------------------------------------------------- canvas helpers
class Canvas:
    """Page canvas at SS x resolution; masks of every drawn unit are kept for the ground truth."""

    def __init__(self, w: int, h: int, color: bool):
        self.w, self.h = w * SS, h * SS
        self.img = np.full((self.h, self.w, 3), 255, np.uint8)
        self.color = color

    def paste_rgba(self, lay: Image.Image, cx: float, cy: float, angle: float = 0.0) -> np.ndarray:
        """Alpha-composite an RGBA layer centred at (cx, cy) in page px; returns its page-sized binary mask."""
        if angle:
            lay = lay.rotate(angle, expand=True, resample=Image.BICUBIC)
        x0, y0 = int(round(cx * SS - lay.width / 2)), int(round(cy * SS - lay.height / 2))
        a = np.asarray(lay)
        mask = np.zeros((self.h, self.w), np.uint8)
        sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(self.w, x0 + lay.width), min(self.h, y0 + lay.height)
        if sx1 <= sx0 or sy1 <= sy0:
            return mask
        sub = a[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0]
        al = sub[..., 3:4].astype(np.float32) / 255
        dst = self.img[sy0:sy1, sx0:sx1].astype(np.float32)
        self.img[sy0:sy1, sx0:sx1] = (dst * (1 - al) + sub[..., :3] * al).astype(np.uint8)
        mask[sy0:sy1, sx0:sx1] = (sub[..., 3] > 40).astype(np.uint8)
        return mask

    def fill_mask(self, mask: np.ndarray, color) -> None:
        self.img[mask > 0] = color

    def result(self) -> np.ndarray:
        return cv2.resize(self.img, (self.w // SS, self.h // SS), interpolation=cv2.INTER_AREA)


def down_mask(m: np.ndarray) -> np.ndarray:
    return cv2.resize(m, (m.shape[1] // SS, m.shape[0] // SS), interpolation=cv2.INTER_AREA) > 0.3


# ---------------------------------------------------------------- panel layout
def layout_rects(page: dict, margin: int = 40, gutter: int = 14, W: int = PAGE_W, H: int = PAGE_H) -> list[list[float]]:
    """`rows: [{h, cols: [w..]}]` -> panel rects [x0,y0,x1,y1] in page px, in reading order (right to left within a row for rtl)."""
    rtl = page.get("reading", "rtl") == "rtl"
    rows = page["rows"]
    inner_w, inner_h = W - 2 * margin, H - 2 * margin
    th = sum(r["h"] for r in rows)
    y = margin
    out = []
    for ri, r in enumerate(rows):
        hh = (inner_h - gutter * (len(rows) - 1)) * r["h"] / th
        tw = sum(r["cols"])
        x = margin
        row = []
        for c in r["cols"]:
            ww = (inner_w - gutter * (len(r["cols"]) - 1)) * c / tw
            row.append([x, y, x + ww, y + hh])
            x += ww + gutter
        out += row[::-1] if rtl else row
        y += hh + gutter
    return out


def koma_rects(page: dict, margin: int = 50, gutter: int = 18, W: int = PAGE_W, H: int = PAGE_H) -> list[list[float]]:
    """Two (or `strips`) vertical 4-koma strips side by side, read right to left, each top to bottom."""
    n = page.get("strips", 2)
    per = page.get("koma", 4)
    top = margin + page.get("header", 0)
    cw = (W - 2 * margin - gutter * (n - 1)) / n
    ch = (H - top - margin - gutter * (per - 1)) / per
    out = []
    for s in range(n):
        x1 = W - margin - s * (cw + gutter)
        for k in range(per):
            y0 = top + k * (ch + gutter)
            out.append([x1 - cw, y0, x1, y0 + ch])
    return out


# ---------------------------------------------------------------- art post-processing
def halftone(gray: np.ndarray, pitch: float, black: float, white: float, gamma: float, angle: float = 45.0) -> np.ndarray:
    """Levels + amplitude-modulated dot screen at `angle` degrees: lines stay solid black, light areas white, midtones become dots."""
    g = np.clip((gray.astype(np.float32) / 255 - black) / (white - black), 0, 1) ** gamma
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = math.radians(angle)
    u = (xx * math.cos(a) + yy * math.sin(a)) / pitch
    v = (-xx * math.sin(a) + yy * math.cos(a)) / pitch
    t = 0.5 + 0.25 * (np.cos(2 * np.pi * u) + np.cos(2 * np.pi * v))
    t = np.clip(t * 0.9 + 0.05, 0.05, 0.95)
    solid_black = g < 0.12
    solid_white = g > 0.88
    out = np.where(g > t, 255, 0).astype(np.uint8)
    out[solid_black] = 0
    out[solid_white] = 255
    return out


def cover(img: np.ndarray, w: int, h: int) -> np.ndarray:
    ih, iw = img.shape[:2]
    s = max(w / iw, h / ih)
    r = cv2.resize(img, (max(w, round(iw * s)), max(h, round(ih * s))), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
    return r[y0:y0 + h, x0:x0 + w]


def place_art(cv: Canvas, rect, art_path: Path, style: dict, panel: dict) -> None:
    x0, y0, x1, y1 = [round(v * SS) for v in rect]
    w, h = x1 - x0, y1 - y0
    if panel.get("fill") == "black":
        cv.img[y0:y1, x0:x1] = 0
        return
    art = cv2.cvtColor(cv2.imread(str(art_path)), cv2.COLOR_BGR2RGB)
    art = cover(art, w, h)
    if not cv.color:
        gray = cv2.cvtColor(art, cv2.COLOR_RGB2GRAY)
        gray, _ = erase_caption_boxes(gray)
        gray = cv2.addWeighted(gray, 1.5, cv2.GaussianBlur(gray, (0, 0), 2.5 * SS), -0.5, 0)  # unsharp: keep the ink lines crisp
        ht = halftone(gray, style.get("pitch", 5.0) * SS, style.get("black", 0.2), style.get("white", 0.82), style.get("gamma", 1.0))
        art = np.dstack([ht] * 3)
    fade = panel.get("fade", 0)
    if fade:  # borderless panel: the art dissolves into the paper
        f = fade * SS
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy))
        al = np.clip(d / f, 0, 1)[..., None]
        art = (art * al + 255 * (1 - al)).astype(np.uint8)
    cv.img[y0:y1, x0:x1] = art


# ---------------------------------------------------------------- shapes
def _ellipse_mask(h, w, cx, cy, rx, ry) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    cv2.ellipse(m, (round(cx * SS), round(cy * SS)), (round(rx * SS), round(ry * SS)), 0, 0, 360, 1, -1, cv2.LINE_AA)
    return m


def _burst_mask(h, w, cx, cy, rx, ry, rng: random.Random, spikes: int = 16) -> np.ndarray:
    pts = []
    for i in range(spikes * 2):
        a = math.pi * i / spikes
        k = 1.28 if i % 2 == 0 else 0.98
        k *= 1 + rng.uniform(-0.05, 0.05)
        pts.append([(cx + math.cos(a) * rx * k) * SS, (cy + math.sin(a) * ry * k) * SS])
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [np.array(pts, np.int32)], 1, cv2.LINE_AA)
    return m


def _cloud_mask(h, w, cx, cy, rx, ry) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    n = 12
    for i in range(n):
        a = 2 * math.pi * i / n
        cv2.circle(m, (round((cx + math.cos(a) * rx * 0.86) * SS), round((cy + math.sin(a) * ry * 0.86) * SS)), round(min(rx, ry) * 0.42 * SS), 1, -1, cv2.LINE_AA)
    cv2.ellipse(m, (round(cx * SS), round(cy * SS)), (round(rx * 0.9 * SS), round(ry * 0.9 * SS)), 0, 0, 360, 1, -1)
    return m


def _tail_mask(h, w, cx, cy, rx, ry, tx, ty, width: float, hook: float = 0.0) -> np.ndarray:
    ang = math.atan2((ty - cy) / ry, (tx - cx) / rx)
    bx, by = cx + math.cos(ang) * rx * 0.82, cy + math.sin(ang) * ry * 0.82
    n = (-math.sin(ang), math.cos(ang))
    p = [(bx + n[0] * width, by + n[1] * width), (tx + hook, ty), (bx - n[0] * width, by - n[1] * width)]
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [np.array([[x * SS, y * SS] for x, y in p], np.int32)], 1, cv2.LINE_AA)
    return m


def _thought_tail(h, w, cx, cy, rx, ry, tx, ty) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    ang = math.atan2((ty - cy) / ry, (tx - cx) / rx)
    bx, by = cx + math.cos(ang) * rx * 1.05, cy + math.sin(ang) * ry * 1.05
    for i, r in enumerate((11, 8, 5)):
        t = (i + 1) / 3.6
        cv2.circle(m, (round((bx + (tx - bx) * t) * SS), round((by + (ty - by) * t) * SS)), r * SS, 1, -1, cv2.LINE_AA)
    return m


def outline_of(mask: np.ndarray, lw: float) -> np.ndarray:
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * round(lw * SS) + 1,) * 2)
    return cv2.dilate(mask, k)


def draw_balloon(cv: Canvas, b: dict, rect, rng: random.Random, fonts_role: str, work_style: dict) -> dict:
    """Draw one balloon (shape + tail + text). Position `at` is in fractions of the panel rect and may leave it (balloons crossing a border)."""
    px0, py0, px1, py1 = rect
    pw, ph = px1 - px0, py1 - py0
    cx, cy = px0 + b["at"][0] * pw, py0 + b["at"][1] * ph
    fs = b.get("fs", work_style.get("fs", 27))
    vertical = b.get("vertical", True)
    shape = b.get("shape", "oval")
    role = b.get("font", fonts_role)
    white = b.get("color") == "white"
    fill = (255, 255, 255, 255) if white else (0, 0, 0, 255)
    halo = shape == "none" and not white
    sw = round(fs * 0.17 * SS) if halo else 0
    lay, (bw, bh) = text_layer(b["text"], role, fs * SS, vertical, fill, sw, (255, 255, 255, 255), align=b.get("align", "mid"))
    bw, bh = bw / SS, bh / SS
    h, w = cv.h, cv.w
    if shape in ("oval", "burst", "thought"):
        k = {"oval": 1.32, "burst": 1.42, "thought": 1.38}[shape]
        rx, ry = bw / 2 * k + fs * 0.6, bh / 2 * k + fs * 0.6
        if shape == "oval" and not vertical:
            rx *= 1.1
        body = {"oval": lambda: _ellipse_mask(h, w, cx, cy, rx, ry), "burst": lambda: _burst_mask(h, w, cx, cy, rx, ry, rng),
                "thought": lambda: _cloud_mask(h, w, cx, cy, rx, ry)}[shape]()
        shp = body
        if b.get("tail"):
            tx, ty = px0 + b["tail"][0] * pw, py0 + b["tail"][1] * ph
            shp = shp | (_thought_tail(h, w, cx, cy, rx, ry, tx, ty) if shape == "thought" else _tail_mask(h, w, cx, cy, rx, ry, tx, ty, fs * 0.42))
        lw = b.get("lw", 3.0 if shape != "burst" else 3.5)
        ring = outline_of(shp, lw)
        cv.fill_mask(ring, (0, 0, 0))
        cv.fill_mask(shp, (255, 255, 255))
        unit_mask = ring
    elif shape == "box":
        rx, ry = bw / 2 + fs * 0.55, bh / 2 + fs * 0.5
        m = np.zeros((h, w), np.uint8)
        cv2.rectangle(m, (round((cx - rx) * SS), round((cy - ry) * SS)), (round((cx + rx) * SS), round((cy + ry) * SS)), 1, -1)
        ring = outline_of(m, b.get("lw", 2.2))
        cv.fill_mask(ring, (0, 0, 0))
        cv.fill_mask(m, (255, 255, 255))
        unit_mask = ring
    else:
        unit_mask = np.zeros((h, w), np.uint8)
    tm = cv.paste_rgba(lay, cx, cy)
    unit_mask = unit_mask | tm
    return dict(mask=unit_mask, text=b["text"], shape=shape, vertical=vertical)


# ---------------------------------------------------------------- sfx / manpu
def draw_sfx(cv: Canvas, s: dict, rect, fonts_role: str) -> dict:
    px0, py0, px1, py1 = rect
    cx, cy = px0 + s["at"][0] * (px1 - px0), py0 + s["at"][1] * (py1 - py0)
    fs = round(s.get("size", 110) * SS)
    vertical = s.get("vertical", False)
    outline = s.get("outline", "white")
    fill = (255, 255, 255, 255) if outline == "black" else (0, 0, 0, 255)
    stroke = (0, 0, 0, 255) if outline == "black" else (255, 255, 255, 255)
    lay, _ = text_layer(s["text"], s.get("font", "dela"), fs, vertical, fill, round(s.get("stroke", 0.09) * fs), stroke, line_gap=1.0, step=0.98)
    if s.get("scale_y"):
        lay = lay.resize((lay.width, round(lay.height * s["scale_y"])), Image.BICUBIC)
    m = cv.paste_rgba(lay, cx, cy, s.get("angle", 0))
    return dict(mask=m, text=s["text"], shape="sfx", vertical=vertical)


def draw_manpu(cv: Canvas, m: dict, rect) -> dict:
    px0, py0, px1, py1 = rect
    pw, ph = px1 - px0, py1 - py0
    cx, cy = px0 + m["at"][0] * pw, py0 + m["at"][1] * ph
    sz = m.get("size", 30)
    h, w = cv.h, cv.w
    mask = np.zeros((h, w), np.uint8)
    kind = m["type"]
    ink = np.zeros((h, w), np.uint8)
    if kind in ("sweat", "tears"):
        n = m.get("n", 1)
        for i in range(n):
            ox, oy = cx + i * sz * 0.9, cy + (i % 2) * sz * 0.5
            pts = []
            for t in np.linspace(0, 2 * math.pi, 40):
                r = sz * 0.5 * (1 - 0.0 * math.cos(t))
                x = ox + r * math.sin(t) * 0.8
                y = oy - r * (math.cos(t) * (1 if math.cos(t) < 0 else 0.75)) + (sz * 0.55 if math.cos(t) < 0 else 0)
                pts.append([x * SS, y * SS])
            cv2.fillPoly(mask, [np.array(pts, np.int32)], 1, cv2.LINE_AA)
        ring = outline_of(mask, 2.0)
        cv.fill_mask(ring, (0, 0, 0))
        cv.fill_mask(mask, (255, 255, 255))
        mask = ring
    elif kind == "anger":
        for qx, qy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            for r, lw in ((sz * 0.5, 4.5),):
                cv2.ellipse(ink, (round((cx + qx * sz * 0.5) * SS), round((cy + qy * sz * 0.5) * SS)), (round(r * SS), round(r * SS)), 0,
                            {(-1, -1): 0, (1, -1): 90, (1, 1): 180, (-1, 1): 270}[(qx, qy)], {(-1, -1): 90, (1, -1): 180, (1, 1): 270, (-1, 1): 360}[(qx, qy)], 1, round(lw * SS), cv2.LINE_AA)
        cv.fill_mask(ink, (0, 0, 0))
        mask = ink
    elif kind == "sparkle":
        for i in range(m.get("n", 1)):
            ox, oy = cx + (i * sz * 1.3) * (1 if i % 2 == 0 else -0.7), cy + i * sz * 0.8
            s = sz * (1 - 0.25 * i)
            pts = np.array([[ox, oy - s], [ox + s * 0.18, oy - s * 0.18], [ox + s, oy], [ox + s * 0.18, oy + s * 0.18],
                            [ox, oy + s], [ox - s * 0.18, oy + s * 0.18], [ox - s, oy], [ox - s * 0.18, oy - s * 0.18]]) * SS
            cv2.fillPoly(mask, [pts.astype(np.int32)], 1, cv2.LINE_AA)
        ring = outline_of(mask, 1.6)
        cv.fill_mask(ring, (0, 0, 0))
        cv.fill_mask(mask, (255, 255, 255))
        mask = ring
    elif kind == "speedlines":
        rng = random.Random(m.get("seed", 3))
        inner = m.get("inner", 0.16) * min(pw, ph)
        x0, y0, x1, y1 = [round(v * SS) for v in rect]
        for i in range(m.get("n", 70)):
            a = rng.uniform(0, 2 * math.pi)
            r0 = inner * rng.uniform(1.0, 2.2)
            r1 = max(pw, ph) * 1.5
            wdt = rng.uniform(0.004, 0.02)
            p = [((cx + math.cos(a) * r0) * SS, (cy + math.sin(a) * r0) * SS), ((cx + math.cos(a + wdt) * r1) * SS, (cy + math.sin(a + wdt) * r1) * SS),
                 ((cx + math.cos(a - wdt) * r1) * SS, (cy + math.sin(a - wdt) * r1) * SS)]
            cv2.fillPoly(ink, [np.array(p, np.int32)], 1, cv2.LINE_AA)
        clip = np.zeros_like(ink)
        clip[y0:y1, x0:x1] = 1
        mask = ink & clip
        cv.fill_mask(mask, (0, 0, 0))
    return dict(mask=mask, text="", shape=kind, vertical=False)


# ---------------------------------------------------------------- work
def render_work(script: dict, art_dir: Path, out_dir: Path) -> dict:
    style = script["style"]
    pages_dir, tdir = out_dir / "pages", out_dir / "truth"
    pages_dir.mkdir(parents=True, exist_ok=True)
    tdir.mkdir(parents=True, exist_ok=True)
    truth = dict(format="ugoku-truth/1", work=script["work"], title=script["title"], reading=script.get("reading", "rtl"), pages=[])
    for pi, page in enumerate(script["pages"]):
        rng = random.Random(1000 * (pi + 1) + script.get("seed", 0))
        color = bool(page.get("color"))
        cv = Canvas(PAGE_W, PAGE_H, color)
        rects = koma_rects(page) if page.get("layout") == "koma" else layout_rects(page, style.get("margin", 40), style.get("gutter", 14))
        for extra in page.get("insets", []):  # free panels given as page fractions, appended after the grid panels
            rects.append([extra["rect"][0] * PAGE_W, extra["rect"][1] * PAGE_H, extra["rect"][2] * PAGE_W, extra["rect"][3] * PAGE_H])
        panels = page["panels"]
        assert len(panels) == len(rects), f"{script['work']} {page['id']}: {len(panels)} panels for {len(rects)} rects"
        bw = page.get("border", style.get("border", 4))
        prect = {}
        for pn, r in zip(panels, rects):
            prect[pn["id"]] = r
            place_art(cv, r, art_dir / f"{page['id']}_{pn['id']}.png", style, pn)
            if pn.get("border", True) and not pn.get("fade"):
                x0, y0, x1, y1 = [round(v * SS) for v in r]
                cv2.rectangle(cv.img, (x0, y0), (x1 - 1, y1 - 1), (0, 0, 0), round(bw * SS))
        units = []
        for item in page.get("items", []):  # drawn in list order; balloon order = list order
            rect = prect[item["panel"]]
            kind = item["kind"]
            if kind == "balloon":
                r = draw_balloon(cv, item, rect, rng, item.get("font", style.get("font", "sans")), style)
            elif kind == "sfx":
                r = draw_sfx(cv, item, rect, style.get("font", "sans"))
            else:
                r = draw_manpu(cv, item, rect)
            units.append(dict(id=item.get("id", f"u{len(units) + 1}"), kind={"balloon": "bubble"}.get(kind, kind), panel=item["panel"], mask=r["mask"],
                              text=r["text"], shape=r["shape"], vertical=r["vertical"], read=kind == "balloon"))
        res = cv.result()
        out_name = f"{page['id']}.png"
        Image.fromarray(res).save(pages_dir / out_name, optimize=True)
        pt = dict(page=page["id"], image=f"pages/{out_name}", w=PAGE_W, h=PAGE_H, color=color, panels=[], units=[], unit_order=[], mask=f"truth/{page['id']}_units.png")
        for i, pn in enumerate(panels):
            x0, y0, x1, y1 = (round(v, 1) for v in prect[pn["id"]])
            pt["panels"].append(dict(id=f"{page['id']}-{pn['id']}", order=i + 1, poly=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]))
        small = np.zeros((PAGE_H, PAGE_W), np.uint8)
        for i, u in enumerate(units, 1):
            dm = down_mask(u["mask"])
            ys, xs = np.where(dm)
            if not len(xs):
                continue
            small[dm & (small == 0)] = i
            uid = f"{page['id']}-{u['id']}"
            pt["units"].append(dict(id=uid, kind=u["kind"], shape=u["shape"], text=u["text"], vertical=u["vertical"], panel=f"{page['id']}-{u['panel']}", label=i,
                                    bbox=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]))
            if u["read"]:
                pt["unit_order"].append(uid)
        Image.fromarray(small).save(out_dir / pt["mask"], optimize=True)
        truth["pages"].append(pt)
    (out_dir / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return truth


def erase_caption_boxes(gray: np.ndarray) -> tuple[np.ndarray, list]:
    """The art model sometimes draws an empty rectangular caption box when asked for free space. Find rectangles made of long straight dark lines
    whose inside is plain white, and wipe them (outline included) to paper white. Returns (cleaned gray, list of boxes x, y, w, h)."""
    h, w = gray.shape
    dark = (gray < 175).astype(np.uint8)
    lh, lv = max(15, int(0.09 * w)), max(15, int(0.06 * h))
    hor = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((1, lh), np.uint8))
    ver = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((lv, 1), np.uint8))
    lines = cv2.dilate(hor | ver, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
    out, boxes = gray.copy(), []
    for i in range(1, n):
        x, y, bw, bh, _a = st[i]
        if bw < 0.12 * w or bh < 0.05 * h or (bw > 0.97 * w and bh > 0.97 * h):
            continue
        inner = gray[y + 8:y + bh - 8, x + 8:x + bw - 8]
        if inner.size == 0 or (inner > 225).mean() < 0.93:
            continue
        comp = (lab[y:y + bh, x:x + bw] == i)
        # all four borders must be present
        ok = comp[:12].any(axis=0).mean() > 0.8 and comp[-12:].any(axis=0).mean() > 0.8 and comp[:, :12].any(axis=1).mean() > 0.8 and comp[:, -12:].any(axis=1).mean() > 0.8
        if ok:
            out[max(0, y - 4):y + bh + 4, max(0, x - 4):x + bw + 4] = 255
            boxes.append((int(x), int(y), int(bw), int(bh)))
    return out, boxes
