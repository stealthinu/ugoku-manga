"""Deterministic reading order for panels and the text units inside them.

Origin: new code (the prototype had the order written by hand in its direction files).
- Panels: recursive XY-cut (rows first), per-row right-to-left (rtl) or left-to-right; 4-koma column layouts are read column by column.
- Units: assigned to the panel holding most of their text pixels; inside a panel, bands by vertical overlap (top to bottom), right to left inside a band.
- SFX / manpu take the start of the panel's motion, not a place in the dialogue sequence.
- Ambiguous pairs can be settled by an LLM; its answers enter as constraints followed by a topological sort.
All boxes are normalized [x0, y0, x1, y1] unless noted.
"""
from __future__ import annotations

import cv2
import numpy as np

from .units import DS, UnitSet


def _xyxy(b):
    return [b[0], b[1], b[0] + b[2], b[1] + b[3]]


# ------------------------------------------------------------------ panels
def _cut(items: list[int], boxes, axis: int, tol: float):
    """Split `items` into groups separated by a free gap along axis (1 = y: horizontal cuts, 0 = x). None if no cut exists."""
    srt = sorted(items, key=lambda i: boxes[i][axis])
    groups, cur, hi = [], [], -1.0
    for i in srt:
        b = boxes[i]
        if cur and b[axis] >= hi - tol:
            groups.append(cur)
            cur, hi = [], -1.0
        cur.append(i)
        hi = max(hi, b[axis + 2])
    groups.append(cur)
    return groups if len(groups) > 1 else None


def _four_koma(boxes, reading: str) -> list[int] | None:
    """One or two columns of >= 3 stacked panels of equal width: read column by column."""
    n = len(boxes)
    if n < 3:
        return None
    cols: list[list[int]] = []
    for i in sorted(range(n), key=lambda i: boxes[i][0]):
        for c in cols:
            ref = boxes[c[0]]
            ov = min(ref[2], boxes[i][2]) - max(ref[0], boxes[i][0])
            if ov > 0.7 * min(ref[2] - ref[0], boxes[i][2] - boxes[i][0]):
                c.append(i)
                break
        else:
            cols.append([i])
    if len(cols) > 2 or any(len(c) < 3 for c in cols):
        return None
    ws = [boxes[i][2] - boxes[i][0] for i in range(n)]
    if max(ws) - min(ws) > 0.12 * max(ws):
        return None
    cols.sort(key=lambda c: -boxes[c[0]][0] if reading == "rtl" else boxes[c[0]][0])
    return [i for c in cols for i in sorted(c, key=lambda i: boxes[i][1])]


def order_panels(bboxes: list, reading: str = "rtl", tol: float = 0.02) -> list[int]:
    """bboxes: [x, y, w, h] normalized. Returns indices in reading order."""
    boxes = [_xyxy(b) for b in bboxes]
    fk = _four_koma(boxes, reading)
    if fk is not None:
        return fk

    def rec(items: list[int]) -> list[int]:
        if len(items) <= 1:
            return list(items)
        for t in (tol, 3 * tol, 5 * tol):  # panel edges that overlap a little still count as a gutter, first with the strictest tolerance
            for axis in (1, 0):
                g = _cut(items, boxes, axis, t)
                if g:
                    if axis == 0 and reading == "rtl":
                        g = g[::-1]
                    return [i for grp in g for i in rec(grp)]
        # no clean cut (overlapping or slanted panels): rows by top edge, right edge descending inside a row
        med = float(np.median([boxes[i][3] - boxes[i][1] for i in items]))
        rows, cur = [], []
        for i in sorted(items, key=lambda i: boxes[i][1]):
            if cur and boxes[i][1] - boxes[cur[0]][1] > 0.5 * med:
                rows.append(cur)
                cur = []
            cur.append(i)
        rows.append(cur)
        return [i for r in rows for i in sorted(r, key=lambda i: -boxes[i][2] if reading == "rtl" else boxes[i][0])]

    return rec(list(range(len(boxes))))


# ------------------------------------------------------------------ units
def assign_units(units: UnitSet, panels: list[dict], hints: dict[str, str] | None = None, straddle: float = 0.25) -> dict[str, str]:
    """unit id -> panel id: largest overlap of the unit's text pixels with the panel polygon (bbox when no polygon); the nearest panel if none overlaps.

    panels: dicts with `id`, `bbox` [x, y, w, h] and optional `poly`.
    hints: unit id -> panel id from the LLM; honoured only when the unit straddles panels (the hinted panel holds >= `straddle` of the best overlap).
    """
    if not panels:
        return {}
    h, w = units.units[0].mask.shape if units.units else (units.H // DS, units.W // DS)
    masks = []
    for p in panels:
        m = np.zeros((h, w), np.uint8)
        poly = p.get("poly") or []
        if len(poly) >= 3:
            cv2.fillPoly(m, [np.array([[x * w, y * h] for x, y in poly], np.int32)], 1)
        else:
            x0, y0, x1, y1 = _xyxy(p["bbox"])
            m[int(y0 * h) : int(np.ceil(y1 * h)), int(x0 * w) : int(np.ceil(x1 * w))] = 1
        masks.append(m > 0)
    out = {}
    for u in units.units:
        src = u.txt if u.txt.any() else u.mask
        ov = [int((src & m).sum()) for m in masks]
        if max(ov) > 0:
            k = int(np.argmax(ov))
            hint = (hints or {}).get(u.id)
            for j, p in enumerate(panels):
                if p["id"] == hint and ov[j] >= straddle * ov[k]:
                    k = j
            out[u.id] = panels[k]["id"]
            continue
        cx, cy = (u.box[0] + u.box[2]) / 2, (u.box[1] + u.box[3]) / 2

        def dist(p):
            x0, y0, x1, y1 = _xyxy(p["bbox"])
            return np.hypot(max(x0 - cx, 0, cx - x1), max(y0 - cy, 0, cy - y1))

        out[u.id] = min(panels, key=dist)["id"]
    return out


def band_order(boxes: list, reading: str = "rtl", min_overlap: float = 0.3) -> list[int]:
    """Order unit boxes inside one panel: bands by vertical overlap (>= 30% of the smaller height), top to bottom, right to left inside a band."""
    idx = sorted(range(len(boxes)), key=lambda i: boxes[i][1])
    bands: list[list[int]] = []
    ext: list[list[float]] = []
    for i in idx:
        b = boxes[i]
        for k, e in enumerate(ext):
            ov = min(e[1], b[3]) - max(e[0], b[1])
            if ov >= min_overlap * min(e[1] - e[0], b[3] - b[1]):
                bands[k].append(i)
                ext[k] = [min(e[0], b[1]), max(e[1], b[3])]
                break
        else:
            bands.append([i])
            ext.append([b[1], b[3]])
    order = sorted(range(len(bands)), key=lambda k: ext[k][0])
    return [i for k in order for i in sorted(bands[k], key=lambda i: -(boxes[i][0] + boxes[i][2]) if reading == "rtl" else boxes[i][0])]


def ambiguous_pairs(boxes: list, order: list[int], reading: str = "rtl", gap_frac: float = 0.15) -> list[tuple[int, int]]:
    """Consecutive pairs (in `order`) whose centre gap along the reading axis is under gap_frac x unit size, or that cross a band boundary."""
    pairs = []
    for a, b in zip(order, order[1:]):
        A, B = boxes[a], boxes[b]
        ov = min(A[3], B[3]) - max(A[1], B[1])
        same_band = ov >= 0.3 * min(A[3] - A[1], B[3] - B[1])
        if same_band:
            size = max(A[2] - A[0], B[2] - B[0])
            gap = abs((A[0] + A[2]) / 2 - (B[0] + B[2]) / 2)
        else:
            size = max(A[3] - A[1], B[3] - B[1])
            gap = abs((A[1] + A[3]) / 2 - (B[1] + B[3]) / 2)
            if ov > 0:  # staggered: neither clearly above nor beside
                pairs.append((a, b))
                continue
        if gap < gap_frac * size:
            pairs.append((a, b))
    return pairs


def apply_constraints(order: list[int], before: list[tuple[int, int]]) -> list[int]:
    """Stable topological sort: keep `order`, but make every (a, b) in `before` hold (a precedes b). Cycles are broken by dropping the later constraint."""
    pos = {v: i for i, v in enumerate(order)}
    cons: list[tuple[int, int]] = []
    for a, b in before:
        if a in pos and b in pos and not _reach(cons, b, a):
            cons.append((a, b))
    out, left = [], list(order)
    while left:
        for v in left:
            if not any(b == v and a in left for a, b in cons):
                out.append(v)
                left.remove(v)
                break
    return out


def _reach(cons, src, dst) -> bool:
    seen, st = set(), [src]
    while st:
        v = st.pop()
        if v == dst:
            return True
        for a, b in cons:
            if a == v and b not in seen:
                seen.add(b)
                st.append(b)
    return False


def sfx_t_in(panel_start: float, offset: float = 0.3) -> float:
    return round(panel_start + offset, 2)
