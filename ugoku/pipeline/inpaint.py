"""Inpainting of masked regions with a manga-tuned LaMa ONNX model.

Origin: the inpaint helpers of the prototype's segmentation module. Each connected hole is cut out with
surrounding context (optionally limited to its panel) and inferred separately.
"""
from __future__ import annotations

import cv2
import numpy as np
import onnxruntime as ort

from ..config import load
from ..models import model_path

_lama: ort.InferenceSession | None = None


def lama_session() -> ort.InferenceSession:
    global _lama
    if _lama is None:
        s = load()
        o = ort.SessionOptions()
        o.intra_op_num_threads = s.threads
        _lama = ort.InferenceSession(str(model_path("lama", s)), o, providers=["CPUExecutionProvider"])
    return _lama


_warned = False


def lama_available() -> bool:
    try:
        model_path("lama")
        return True
    except FileNotFoundError:
        return False


def lama_run(img: np.ndarray, m: np.ndarray) -> np.ndarray:
    global _warned
    if _lama is None and not lama_available():  # no inpainting model installed: plain OpenCV fill (lower quality, enough for a first try)
        if not _warned:
            import sys

            print("warning: lama-manga-dynamic.onnx not found; using OpenCV inpainting (lower quality)", file=sys.stderr)
            _warned = True
        return cv2.inpaint(np.ascontiguousarray(img), (m > 0).astype(np.uint8) * 255, 5, cv2.INPAINT_TELEA)
    H, W = m.shape
    ph, pw = (-H) % 8, (-W) % 8
    im = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="reflect")
    mm = np.pad(m, ((0, ph), (0, pw)))
    x = im[:, :, ::-1].astype(np.float32).transpose(2, 0, 1)[None] / 255
    mk = (mm > 0).astype(np.float32)[None, None]
    o = lama_session().run(None, {"image": x, "mask": mk})[0][0].transpose(1, 2, 0)
    return np.clip(o * 255 + 0.5, 0, 255).astype(np.uint8)[:H, :W, ::-1]


def inpaint(img, m, ctx=48, gray=True, bounds=None, full_mask=None):
    """Fill m>0. One inference per connected hole (bbox + context; big holes get more context).

    bounds=[x0,y0,x1,y1] limits the context window (e.g. to a panel). Deep holes (>30 px from the edge)
    whose centre drifts from the surrounding median are pulled back toward that median.
    """
    m = (m > 0).astype(np.uint8)
    out = img.copy()
    if not m.any():
        return out
    H, W = m.shape
    bx0, by0, bx1, by1 = bounds or (0, 0, W, H)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(m, np.ones((15, 15), np.uint8)), connectivity=8)
    for i in range(1, n):
        x, y, w, h, _ = st[i]
        c = max(ctx, int(0.35 * max(w, h)))
        x0, y0, x1, y1 = max(bx0, x - c), max(by0, y - c), min(bx1, x + w + c), min(by1, y + h + c)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        mm = m[y0:y1, x0:x1] * (lab[y0:y1, x0:x1] == i)
        if not mm.any() or mm.all():
            continue
        # other holes inside the window are passed as unknown too, so remnants of letters do not get extended
        ma = m[y0:y1, x0:x1] if full_mask is None else ((mm > 0) | (full_mask[y0:y1, x0:x1] > 0)).astype(np.uint8)
        o = lama_run(out[y0:y1, x0:x1], ma)
        if gray:
            o = cv2.cvtColor(cv2.cvtColor(o, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        d = cv2.distanceTransform(mm, cv2.DIST_L2, 5)
        if d.max() > 30:
            ring = (cv2.dilate(mm, np.ones((9, 9), np.uint8)) - mm) > 0
            med = np.median(out[y0:y1, x0:x1][ring], axis=0)
            deep = d > 30
            if abs(float(o[deep].mean()) - float(med.mean())) > 45:
                wgt = np.clip((d - 22) / 40, 0, 0.8)[..., None]
                o = (o * (1 - wgt) + med * wgt).astype(np.uint8)
        a = cv2.GaussianBlur(cv2.dilate(mm, np.ones((3, 3), np.uint8)).astype(np.float32), (0, 0), 0.8)[..., None]
        out[y0:y1, x0:x1] = (out[y0:y1, x0:x1] * (1 - a) + o * a).astype(np.uint8)
    return out


def inpaint_page(img, m, panel_rects):
    """Fill panel by panel with context limited to the panel (smallest first), then the remainder with page context."""
    m = (m > 0).astype(np.uint8)
    out = img.copy()
    rest = m.copy()
    for r in sorted(panel_rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1])):
        x0, y0, x1, y1 = r
        sub = np.zeros_like(m)
        sub[y0:y1, x0:x1] = rest[y0:y1, x0:x1]
        if not sub.any():
            continue
        out = inpaint(out, sub, bounds=r, full_mask=rest)
        rest &= 1 - sub
    return inpaint(out, rest) if rest.any() else out


def fill_difficulty(img, m, panel=None):
    """(depth px, flatness) of the hole. Flatness = share of the surrounding ring within +-30 of its median."""
    m = (m > 0).astype(np.uint8)
    if panel is not None:
        x0, y0, x1, y1 = panel
        c = np.zeros_like(m)
        c[y0:y1, x0:x1] = 1
        m = m & c
    if not m.any():
        return 0.0, 1.0
    d = float(cv2.distanceTransform(m, cv2.DIST_L2, 5).max())
    ring = (cv2.dilate(m, np.ones((15, 15), np.uint8)) - cv2.dilate(m, np.ones((3, 3), np.uint8))) > 0
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.5)[ring]
    if g.size == 0:
        return d, 1.0
    return d, float((np.abs(g - np.median(g)) < 30).mean())


def hard_to_fill(img, m, panel=None, depth=38, flat=0.62):
    """Deeper holes need a flatter surround (38 px -> 0.62, 70 px -> 0.85, capped)."""
    d, f = fill_difficulty(img, m, panel)
    need = min(0.85, flat + max(0.0, d - depth) / 140)
    return d > depth and f < need, d, f
