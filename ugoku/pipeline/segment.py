"""Cutting text units out of a page: balloons, free text and SFX, as pixel masks.

Origin: the prototype's segmentation module plus its fallback SFX cutter.
- Balloon: the detector box is the unit. The mask is the white area closed by the outline (outline included).
  Balloons that blend into white (no closed outline) fall back to text pixels plus a white halo.
- SFX: text pixels grouped into words by dilation; the groups overlapping a reference rect are taken whole.
"""
from __future__ import annotations

import cv2
import numpy as np

from .detect.text import bubbles, text_probability

K3 = np.ones((3, 3), np.uint8)


def overlap(a, b) -> float:
    """Intersection / area of the smaller box."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    s = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / max(1, s)


def cut_dark_components(gray, rect, thr=90, pad=10, light=False):
    """Fallback cutter: dark (or light) connected components inside rect+pad, not touching the pad border; hollow letters are filled."""
    H, W = gray.shape
    x0, y0, x1, y1 = rect
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    dark = ((gray[Y0:Y1, X0:X1] > 170) if light else (gray[Y0:Y1, X0:X1] < thr)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    m = np.zeros(gray.shape, np.uint8)
    h, w = dark.shape
    rect_area = (x1 - x0) * (y1 - y0)
    for i in range(1, n):
        x, y, cw, ch, a = st[i]
        if a < 12:
            continue
        if (x <= 0 and X0 > 0) or (y <= 0 and Y0 > 0) or (x + cw >= w and X1 < W) or (y + ch >= h and Y1 < H):
            continue  # touches the pad border: connected to the background
        if cw * ch > 1.6 * rect_area:
            continue
        m[Y0:Y1, X0:X1] |= (lab == i).astype(np.uint8)
    sub = m[Y0:Y1, X0:X1].copy()
    fm = np.zeros((h + 2, w + 2), np.uint8)
    fl = (1 - sub).astype(np.uint8)
    cv2.floodFill(fl, fm, (0, 0), 2)
    holes = fl == 1  # background not reachable from outside
    nh, hl, hs, _ = cv2.connectedComponentsWithStats(holes.astype(np.uint8), connectivity=4)
    for j in range(1, nh):
        if hs[j, 4] <= 0.25 * max(1, rect_area):  # only small holes, not big white areas of the drawing
            sub[hl == j] = 1
    m[Y0:Y1, X0:X1] = sub
    return m


class Page:
    """Detected text units of one page. `units`: dict(kind='balloon'|'free', box=[x0,y0,x1,y1], mask=HxW uint8)."""

    def __init__(self, img: np.ndarray):
        self.img = img
        self.H, self.W = img.shape[:2]
        self.gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self.seg = text_probability(img)
        self.txt = (self.seg > 0.3).astype(np.uint8)
        dets = bubbles(img, 0.3)
        boxes = [b for lab, b, _s in dets if lab == 0]

        def inside(b, c):
            return b[0] >= c[0] - 6 and b[1] >= c[1] - 6 and b[2] <= c[2] + 6 and b[3] <= c[3] + 6

        self.units = [dict(kind="balloon", box=self._ib(b)) for b in boxes]
        for lab, b, _s in dets:  # text boxes outside any balloon: narration or missed balloons
            if lab in (1, 2) and not any(inside(b, c) for c in boxes):
                self.units.append(dict(kind="free", box=self._ib(b)))
        self._dedupe()
        for u in self.units:
            u["mask"] = self.unit_mask(u)
        self.units = [u for u in self.units if int(u["mask"].sum()) >= 40]  # boxes without text are false positives

    def _ib(self, b):
        return [max(0, int(b[0]) - 2), max(0, int(b[1]) - 2), min(self.W, int(np.ceil(b[2])) + 2), min(self.H, int(np.ceil(b[3])) + 2)]

    def _dedupe(self):
        keep = []
        for u in sorted(self.units, key=lambda u: -(u["box"][2] - u["box"][0]) * (u["box"][3] - u["box"][1])):
            if any(u["kind"] == k["kind"] and overlap(u["box"], k["box"]) > 0.8 for k in keep):
                continue
            keep.append(u)
        self.units = keep

    def unit_mask(self, u):
        x0, y0, x1, y1 = u["box"]
        H, W = self.H, self.W
        m = np.zeros((H, W), np.uint8)
        g = self.gray[y0:y1, x0:x1]
        t = self.txt[y0:y1, x0:x1]
        h, w = g.shape
        if u["kind"] == "balloon":
            dark = (g < 150).astype(np.uint8)
            closed = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            inv = (1 - closed).astype(np.uint8)  # white that cannot reach the box edge = inside the outline
            pad = cv2.copyMakeBorder(inv, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=1)
            # a balloon cut by the page edge: that side is a wall
            if x0 <= 3:
                pad[:, 0] = 0
            if y0 <= 3:
                pad[0, :] = 0
            if x1 >= W - 3:
                pad[:, -1] = 0
            if y1 >= H - 3:
                pad[-1, :] = 0
            ff = pad.copy()
            fm = np.zeros((h + 4, w + 4), np.uint8)
            seeds = [(0, 0), (0, w + 1), (h + 1, 0), (h + 1, w + 1), (0, w // 2), (h + 1, w // 2), (h // 2, 0), (h // 2, w + 1)]
            for sy, sx in seeds:
                if ff[sy, sx] == 1:
                    cv2.floodFill(ff, fm, (sx, sy), 2)
            inner = (ff[1:-1, 1:-1] == 1).astype(np.uint8)
            n, lab, st, _ = cv2.connectedComponentsWithStats(inner, connectivity=4)
            body = np.zeros_like(inner)
            for i in range(1, n):
                comp = lab == i
                if st[i, 4] > 0.04 * h * w and (t[comp].sum() > 0 or st[i, 4] > 0.2 * h * w):
                    body |= comp.astype(np.uint8)
            if body.sum() > 0.12 * h * w:
                cn, _ = cv2.findContours(body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                f = np.zeros_like(body)
                cv2.drawContours(f, cn, -1, 1, -1)
                ring = cv2.dilate(f, np.ones((9, 9), np.uint8)) & (1 - f)  # outline: dark pixels within 4 px outside the interior
                line = ring & cv2.dilate((g < 200).astype(np.uint8), K3)
                f = f | line
                f = cv2.morphologyEx(f, cv2.MORPH_CLOSE, K3)
                f = cv2.dilate(f, K3)
                u["closed"] = True
            else:  # outline not closed inside the box (joined balloons, cut by a panel border, blends into white)
                f = self._white_body(g, t)
                u["closed"] = False
                if self._last_textonly:
                    u["textonly"] = True  # shape not found: keep the balloon in the base, only the text appears
        else:
            f = self._free(g, t, white_halo=True)
        m[y0:y1, x0:x1] = f
        if u.get("closed"):
            m = self._tail(m, u["box"])
        return m

    _last_textonly = False

    def _tail(self, m, box, e=14):
        """Balloon tail: small dark strokes touching the mask within box+e px."""
        x0, y0, x1, y1 = max(0, box[0] - e), max(0, box[1] - e), min(self.W, box[2] + e), min(self.H, box[3] + e)
        d = (self.gray[y0:y1, x0:x1] < 150).astype(np.uint8)
        sub = m[y0:y1, x0:x1]
        ba = (box[2] - box[0]) * (box[3] - box[1])
        n, lab, st, _ = cv2.connectedComponentsWithStats(d & (1 - sub), connectivity=8)
        touch = cv2.dilate(sub, np.ones((5, 5), np.uint8))
        for i in range(1, n):
            small = st[i, 4] < 0.03 * ba
            free_of_edges = st[i, 0] > 0 and st[i, 1] > 0 and st[i, 0] + st[i, 2] < x1 - x0 and st[i, 1] + st[i, 3] < y1 - y0
            if small and touch[lab == i].any() and free_of_edges:
                sub |= cv2.dilate((lab == i).astype(np.uint8), K3)
        m[y0:y1, x0:x1] = sub
        return m

    def _white_body(self, g, t):
        wt = (g > 200).astype(np.uint8)
        seed = cv2.dilate(t, np.ones((5, 5), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(wt, connectivity=4)
        body = np.zeros_like(wt)
        for i in range(1, n):
            comp = lab == i
            if seed[comp].any() and st[i, 4] >= 30:
                body |= comp.astype(np.uint8)
        edge = np.concatenate([body[0], body[-1], body[:, 0], body[:, -1]])
        if body.sum() > 0.7 * body.size or edge.mean() > 0.3:  # white fills the box: text on white, not a balloon
            self._last_textonly = True
            return self._free(g, t, white_halo=True)
        self._last_textonly = False
        body |= self._free(g, t, white_halo=False)
        body = cv2.morphologyEx(body, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        cn, _ = cv2.findContours(body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        f = np.zeros_like(body)
        cv2.drawContours(f, cn, -1, 1, -1)
        ring = cv2.dilate(f, np.ones((9, 9), np.uint8)) & (1 - f)
        line = ring & (g < 200).astype(np.uint8)
        return cv2.dilate(f | line, K3)

    def _free(self, g, t, white_halo):
        f = cv2.dilate(t, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        if white_halo:  # white-edged letters over black or art: include the white around them
            halo = cv2.dilate(f, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) & (g > 200).astype(np.uint8)
            f = f | halo
        return f

    # ---- SFX ----
    def sfx_groups(self, exclude, gap=9):
        t = self.txt & (1 - (exclude > 0).astype(np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(t, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gap, gap))), connectivity=8)
        return [(lab == i) & (t > 0) for i in range(1, n) if st[i, 4] >= 60]

    def sfx_mask(self, rect_px, groups, clip=None):
        """Word groups overlapping rect, whole (including parts outside rect), plus heavy outline and hollow interiors."""
        x0, y0, x1, y1 = rect_px
        ra = max(1, (x1 - x0) * (y1 - y0))
        sel = np.zeros((self.H, self.W), bool)
        for gm in groups:
            ys, xs = np.where(gm)
            inter = ((xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)).sum()
            if inter >= 0.25 * len(xs) or inter >= 0.15 * ra:
                sel |= gm
        if not sel.any():
            return None
        m = sel.astype(np.uint8)
        near = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))  # thick black or white edging near the letters
        ink = near & (((self.gray < 110) | (self.gray > 225)).astype(np.uint8))
        m = m | ink
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        cn, _ = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        f = m.copy()
        for c in cn:
            if cv2.contourArea(c) < 0.3 * ra:
                cv2.drawContours(f, [c], -1, 1, -1)
        f = cv2.dilate(f, K3)
        if clip is not None:
            f &= clip
        return f


def match_by_rect(units, rects, sfx_rects=()):
    """Assign detected units to direction rects (one unit -> the best-overlapping rect).

    Used when a direction file refers to units by rectangle instead of by id. A free-text unit that overlaps an
    SFX rect better than any balloon rect is flagged as SFX. Returns ({rect_idx: [unit_idx]}, [unassigned unit_idx]).
    """
    res = {i: [] for i in range(len(rects))}
    free = []
    for j, u in enumerate(units):
        best = max([(overlap(u["box"], r), i) for i, r in enumerate(rects)], default=(0, -1))
        sb = max([overlap(u["box"], r) for r in sfx_rects], default=0)
        if u["kind"] == "free" and sb >= 0.35 and sb > best[0]:
            u["sfx"] = True
            continue
        if best[0] >= 0.35:
            res[best[1]].append(j)
        else:
            free.append(j)
    # second pass: rects without a unit take the closest leftover (direction rects can be a little off)
    for i, r in enumerate(rects):
        if res[i] or not free:
            continue
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        diag = np.hypot(r[2] - r[0], r[3] - r[1])

        def key(j, r=r, cx=cx, cy=cy):
            b = units[j]["box"]
            return (-round(overlap(b, r), 2), np.hypot((b[0] + b[2]) / 2 - cx, (b[1] + b[3]) / 2 - cy))

        j = min(free, key=key)
        b = units[j]["box"]
        if overlap(b, r) > 0.05 or np.hypot((b[0] + b[2]) / 2 - cx, (b[1] + b[3]) / 2 - cy) < 0.8 * diag:
            res[i].append(j)
            free.remove(j)
    return res, free
