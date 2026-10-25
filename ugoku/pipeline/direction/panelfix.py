"""Apply the LLM's panel corrections to the detector's candidates. The LLM only picks ids and rough positions; edges come from the image."""
from __future__ import annotations

import numpy as np

from ..panels import snap_cut, snap_to_gutters


def _union(boxes):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def _rect_poly(b):
    return [[b[0], b[1]], [b[0] + b[2], b[1]], [b[0] + b[2], b[1] + b[3]], [b[0], b[1] + b[3]]]


def apply_panel_fixes(img: np.ndarray, cands: list[dict], fixes: list[dict]) -> tuple[list[dict], list[str]]:
    """cands: [{id, bbox, poly, source}]. Returns (panels with `src` = id used in the LLM's descriptions, log).

    ops: confirm (no change), not_panel (drop), merge (union under the first id), split (two halves `<id>a`, `<id>b`), add (new `N<k>`).
    Candidates the LLM did not mention stay as they are.
    """
    by = {c["id"]: dict(c, src=c["id"]) for c in cands}
    log: list[str] = []
    n_new = 0
    for f in fixes:
        op, ids = f.get("op"), [i for i in f.get("ids", []) if i in by]
        if op == "not_panel":
            for i in ids:
                by.pop(i)
                log.append(f"drop {i}")
        elif op == "merge" and len(ids) >= 2:
            bb = _union([by[i]["bbox"] for i in ids])
            keep = ids[0]
            for i in ids[1:]:
                by.pop(i)
            by[keep].update(bbox=bb, poly=_rect_poly(bb), source="llm_merge")
            log.append("merge " + "+".join(ids))
        elif op == "split" and len(ids) == 1 and f.get("axis") in ("x", "y") and f.get("approx_pos") is not None:
            c = by[ids[0]]
            x, y, w, h = c["bbox"]
            pos = snap_cut(img, c["bbox"], f["axis"], float(f["approx_pos"]))
            lo, hi = (y, y + h) if f["axis"] == "y" else (x, x + w)
            if not (lo + 0.05 * (hi - lo) < pos < hi - 0.05 * (hi - lo)):
                log.append(f"split {ids[0]} ignored (position outside)")
                continue
            if f["axis"] == "y":
                a, b = [x, y, w, pos - y], [x, pos, w, y + h - pos]
            else:
                a, b = [x, y, pos - x, h], [pos, y, x + w - pos, h]
            by.pop(ids[0])
            by[ids[0] + "a"] = dict(id=ids[0] + "a", bbox=a, poly=_rect_poly(a), score=c.get("score", 1), source="llm_split", src=ids[0] + "a")
            by[ids[0] + "b"] = dict(id=ids[0] + "b", bbox=b, poly=_rect_poly(b), score=c.get("score", 1), source="llm_split", src=ids[0] + "b")
            log.append(f"split {ids[0]} {f['axis']}@{pos:.3f}")
        elif op == "add" and f.get("approx_rect") and len(f["approx_rect"]) == 4:
            r = [float(v) for v in f["approx_rect"]]
            r = [max(0.0, r[0]), max(0.0, r[1]), min(1.0 - max(0.0, r[0]), r[2]), min(1.0 - max(0.0, r[1]), r[3])]
            if r[2] < 0.08 or r[3] < 0.05:
                continue
            bb = snap_to_gutters(img, r)
            n_new += 1
            pid = f"N{n_new}"
            by[pid] = dict(id=pid, bbox=bb, poly=_rect_poly(bb), score=0.5, source="llm_add", src=pid)
            log.append(f"add {pid}")
    return list(by.values()), log
