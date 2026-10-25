"""Automatic panel detection (classical, CPU only).

Origin: the prototype's white-gutter panel finder, hardened:
- the gutter colour comes from the page border (light or dark gutters), not a fixed threshold
- a 1 px pad plus exterior flood fill, morphological opening, connected components, polygon approximation
- recursive XY-cut on the pixel profile splits panels that touch at a corner; slivers left by a cut are merged back
Output: `Panel(id, bbox=[x,y,w,h] normalized, poly=[[x,y]..] normalized, score, source)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

MIN_AREA, MIN_W, MIN_H = 0.015, 0.10, 0.05
SLIVER = 0.02
MIN_RECT = 0.88  # balloons (ellipses ~0.79) and lettering blobs are not panels; slanted panels still score ~1.0


@dataclass
class Panel:
    id: str
    bbox: list  # [x, y, w, h], normalized to the page
    poly: list = field(default_factory=list)
    score: float = 1.0
    source: str = "classical"

    def to_dict(self) -> dict:
        return dict(id=self.id, bbox=[round(v, 5) for v in self.bbox], poly=[[round(x, 5), round(y, 5)] for x, y in self.poly], score=round(self.score, 3), source=self.source)


def gutter_mask(gray: np.ndarray) -> np.ndarray:
    """Pixels with the gutter colour (1 = gutter). The colour is estimated from the page border; dark gutters are handled by inversion."""
    H, W = gray.shape
    b = max(2, int(0.012 * min(H, W)))
    border = np.concatenate([gray[:b].ravel(), gray[-b:].ravel(), gray[:, :b].ravel(), gray[:, -b:].ravel()])
    if (border > 200).mean() >= 0.5:
        ref = float(np.median(border[border > 200]))
        thr = int(np.clip(ref - 20, 200, 240))
        return (gray > thr).astype(np.uint8)
    if (border < 55).mean() >= 0.5:
        ref = float(np.median(border[border < 55]))
        thr = int(np.clip(ref + 20, 15, 60))
        return (gray < thr).astype(np.uint8)
    return (gray > 235).astype(np.uint8)


def _components(non: np.ndarray, min_dim: float = 0.0):
    n, lab, st, _ = cv2.connectedComponentsWithStats(non, connectivity=4)
    return [(i, st[i]) for i in range(1, n)]


def _line_cut(dark: np.ndarray, axis: int) -> int | None:
    """Position of a thin dark panel-border line crossing `dark` (1 = ink), or None.

    The row (axis 0) / column (axis 1) ink profile of a drawn border is a narrow spike; solid black art is a wide plateau, not a spike.
    """
    h, w = dark.shape
    n = h if axis == 0 else w
    prof = dark.mean(axis=1 - axis).astype(np.float32)
    k = max(6, int(0.008 * n))
    best, pos = 0.0, None
    for r in range(int(0.08 * n), int(0.92 * n)):
        lo, hi = max(0, r - k), min(n - 1, r + k)
        spike = prof[r] - max(prof[lo], prof[hi])
        if prof[r] >= 0.8 and spike >= 0.5 and spike > best:
            best, pos = spike, r
    return pos


def _xy_cut(mask: np.ndarray, dark: np.ndarray, x0: int, y0: int, depth: int = 0, min_gap_frac: float = 0.008, fill_thr: float = 0.02) -> list[tuple[int, int, int, int]]:
    """Split `mask` (1 = panel pixels) at runs of rows/columns that are almost empty, or at thin border lines. Returns boxes in page pixels."""
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return []
    ty0, ty1, tx0, tx1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    mask, dark = mask[ty0:ty1, tx0:tx1], dark[ty0:ty1, tx0:tx1]
    x0, y0 = x0 + tx0, y0 + ty0
    h, w = mask.shape
    if depth < 6:
        for axis in (0, 1):  # 0: cut between rows (horizontal gutter), 1: between columns
            prof = mask.sum(axis=1 - axis).astype(np.float32) / (w if axis == 0 else h)
            empty = prof < fill_thr
            n = h if axis == 0 else w
            gap_min = max(2, int(min_gap_frac * n * (1 if n > 100 else 0)))
            i = 1
            while i < n - 1:
                if empty[i]:
                    j = i
                    while j < n and empty[j]:
                        j += 1
                    if j - i >= gap_min and i > 0.03 * n and n - j > 0.03 * n:
                        if axis == 0:
                            return _xy_cut(mask[:i], dark[:i], x0, y0, depth + 1) + _xy_cut(mask[j:], dark[j:], x0, y0 + j, depth + 1)
                        return _xy_cut(mask[:, :i], dark[:, :i], x0, y0, depth + 1) + _xy_cut(mask[:, j:], dark[:, j:], x0 + j, y0, depth + 1)
                    i = j
                else:
                    i += 1
        if w * h > 0.04 * W_PAGE_AREA.get():  # border-line cuts only inside big blobs (borderless layouts)
            for axis in (0, 1):
                r = _line_cut(dark, axis)
                if r is not None:
                    if axis == 0:
                        return _xy_cut(mask[: r - 1], dark[: r - 1], x0, y0, depth + 1) + _xy_cut(mask[r + 2 :], dark[r + 2 :], x0, y0 + r + 2, depth + 1)
                    return _xy_cut(mask[:, : r - 1], dark[:, : r - 1], x0, y0, depth + 1) + _xy_cut(mask[:, r + 2 :], dark[:, r + 2 :], x0 + r + 2, y0, depth + 1)
    return [(x0, y0, x0 + w, y0 + h)]


class _Area:
    """Page pixel area of the image being processed (thread-local would be overkill: detection is single-threaded per process)."""

    v = 1

    def get(self):
        return self.v


W_PAGE_AREA = _Area()


def detect_panels(img: np.ndarray, min_area: float = MIN_AREA) -> list[Panel]:
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    gut = gutter_mask(gray)
    W_PAGE_AREA.v = W * H
    dark_img = (gray < 110).astype(np.uint8)
    pad = cv2.copyMakeBorder(gut, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=1)
    _, lab = cv2.connectedComponents(pad, connectivity=4)
    ext = (lab == lab[0, 0])[1:-1, 1:-1]
    non = (~ext).astype(np.uint8)
    k = max(3, int(round(0.004 * min(H, W))) | 1)
    non = cv2.morphologyEx(non, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(non, connectivity=4)
    boxes: list[tuple[int, int, int, int, np.ndarray, int, int]] = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if w * h < 0.5 * min_area * W * H:
            continue
        comp = (lab[y : y + h, x : x + w] == i).astype(np.uint8)
        for bx in _xy_cut(comp, dark_img[y : y + h, x : x + w].copy(), x, y):
            boxes.append((*bx, comp, x, y))
    out_boxes = []
    for x0, y0, x1, y1, comp, cx, cy in boxes:
        w, h = x1 - x0, y1 - y0
        if w * h > min_area * W * H and w > MIN_W * W and h > MIN_H * H and _rectangularity(comp[y0 - cy : y1 - cy, x0 - cx : x1 - cx]) >= MIN_RECT:
            out_boxes.append((x0, y0, x1, y1))
    out_boxes = _merge_slivers(out_boxes, W, H)
    panels = []
    for x0, y0, x1, y1 in out_boxes:
        sub = (lab[y0:y1, x0:x1] > 0).astype(np.uint8)
        poly = _polygon(sub, x0, y0, W, H)
        score = float(sub.mean())
        panels.append(Panel(id="", bbox=[x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H], poly=poly, score=score))
    return panels


def _rectangularity(sub: np.ndarray) -> float:
    """Convex-hull area of the largest blob over the area of its minimum-area rotated rectangle."""
    cn, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cn:
        return 0.0
    c = cv2.convexHull(max(cn, key=cv2.contourArea))  # hull: balloons overlapping the gutter bite notches into a panel, the hull restores it
    (_, (rw, rh), _) = cv2.minAreaRect(c)
    return float(cv2.contourArea(c) / max(1.0, rw * rh))


def _merge_slivers(boxes, W, H):
    """Boxes smaller than SLIVER of the page that touch a bigger box (gap < 1.5% of the page) are absorbed by it."""
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        for i, b in enumerate(boxes):
            area = (b[2] - b[0]) * (b[3] - b[1]) / (W * H)
            if area >= SLIVER:
                break
            for j in range(len(boxes) - 1, i, -1):
                o = boxes[j]
                gx = max(o[0] - b[2], b[0] - o[2], 0) / W
                gy = max(o[1] - b[3], b[1] - o[3], 0) / H
                ox = min(o[2], b[2]) - max(o[0], b[0])
                oy = min(o[3], b[3]) - max(o[1], b[1])
                if (gx < 0.015 and oy > 0.5 * (b[3] - b[1])) or (gy < 0.015 and ox > 0.5 * (b[2] - b[0])):
                    o[0], o[1], o[2], o[3] = min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])
                    boxes.pop(i)
                    changed = True
                    break
            if changed:
                break
    return [tuple(b) for b in boxes]


def _polygon(sub: np.ndarray, x0: int, y0: int, W: int, H: int) -> list:
    cn, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cn:
        h, w = sub.shape
        return [[x0 / W, y0 / H], [(x0 + w) / W, y0 / H], [(x0 + w) / W, (y0 + h) / H], [x0 / W, (y0 + h) / H]]
    c = max(cn, key=cv2.contourArea)
    eps = 0.01 * cv2.arcLength(c, True)
    ap = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
    if len(ap) > 12:
        ap = cv2.convexHull(ap).reshape(-1, 2)
        ap = cv2.approxPolyDP(ap.reshape(-1, 1, 2), eps * 2, True).reshape(-1, 2)
    return [[(x0 + int(px)) / W, (y0 + int(py)) / H] for px, py in ap]


def snap_to_gutters(img: np.ndarray, bbox: list, max_shift: float = 0.03) -> list:
    """Snap each edge of a normalized bbox to the nearest panel edge found by the classical detector within `max_shift` of the page.

    The LLM never supplies final coordinates: its proposed edges are moved onto detected lines (or kept if nothing is near).
    """
    H, W = img.shape[:2]
    cand = detect_panels(img, min_area=0.005)
    xs = [p.bbox[0] for p in cand] + [p.bbox[0] + p.bbox[2] for p in cand] + [0.0, 1.0]
    ys = [p.bbox[1] for p in cand] + [p.bbox[1] + p.bbox[3] for p in cand] + [0.0, 1.0]

    def snap(v, arr):
        best = min(arr, key=lambda a: abs(a - v))
        return best if abs(best - v) <= max_shift else v

    x0, y0, x1, y1 = bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]
    x0, x1, y0, y1 = snap(x0, xs), snap(x1, xs), snap(y0, ys), snap(y1, ys)
    return [x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)]


def snap_cut(img: np.ndarray, bbox: list, axis: str, pos: float, window: float = 0.03) -> float:
    """Snap a proposed cut position (page fraction along `axis`, "x" or "y") inside `bbox` to the best gutter or border line within `window` of the page.

    Score of a line = max(share of gutter-coloured pixels, border-line ink spike); the proposal is kept when nothing scores well.
    """
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    gut = gutter_mask(gray).astype(np.float32)
    ink = (gray < 110).astype(np.float32)
    x0, y0, x1, y1 = int(bbox[0] * W), int(bbox[1] * H), int((bbox[0] + bbox[2]) * W), int((bbox[1] + bbox[3]) * H)
    if axis == "y":
        n, lo, hi = H, y0, y1
        g, k = gut[y0:y1, x0:x1].mean(axis=1), ink[y0:y1, x0:x1].mean(axis=1)
    else:
        n, lo, hi = W, x0, x1
        g, k = gut[y0:y1, x0:x1].mean(axis=0), ink[y0:y1, x0:x1].mean(axis=0)
    c = int(pos * n)
    best, best_s = pos, 0.5
    r = max(2, int(window * n))
    for i in range(max(lo + int(0.05 * (hi - lo)), c - r), min(hi - int(0.05 * (hi - lo)), c + r)):
        j = i - lo
        sp = k[j] - max(k[max(0, j - 8)], k[min(len(k) - 1, j + 8)])
        s = max(float(g[j]), float(sp) + 0.2 if k[j] > 0.6 else 0.0) - 0.002 * abs(i - c) / max(1, r) * 100 * 0.01
        if s > best_s:
            best, best_s = i / n, s
    return best
