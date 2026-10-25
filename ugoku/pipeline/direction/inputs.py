"""Images shown to the LLM: the page, a set-of-marks overlay (panel ids, unit ids, ruler) and one labelled crop per panel."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

KIND_COLOR = {"balloon": (200, 90, 0), "free": (0, 150, 0), "sfx": (0, 0, 220)}  # BGR
PANEL_COLORS = [(0, 0, 255), (255, 0, 255), (0, 140, 255), (200, 120, 0)]
MAX_SIDE = 1600


def _fit(img: np.ndarray, side: int = MAX_SIDE) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    k = min(1.0, side / max(h, w))
    return (cv2.resize(img, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else img), k


def _label(img, text, org, color, scale, thick=2):
    (tw, th), bl = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    x, y = org
    x, y = max(0, min(x, img.shape[1] - tw - 4)), max(th + 4, min(y, img.shape[0] - 2))
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 4, y + bl), (255, 255, 255), -1)
    cv2.putText(img, text, (x + 2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def overlay_image(img: np.ndarray, panels: list[dict], units: list[tuple[str, str, list]], ruler: bool = True) -> np.ndarray:
    """panels: [{id, bbox}], units: [(id, kind, box normalized xyxy)]. Returns the page with marks and a 10% ruler margin."""
    base, _ = _fit(img)
    H, W = base.shape[:2]
    canvas = base.copy()
    for i, p in enumerate(panels):
        x, y, w, h = p["bbox"]
        c = PANEL_COLORS[i % len(PANEL_COLORS)]
        cv2.rectangle(canvas, (round(x * W), round(y * H)), (round((x + w) * W), round((y + h) * H)), c, 4)
        _label(canvas, p["id"], (round(x * W) + 6, round(y * H) + 44), c, 1.4, 3)
    for uid, kind, b in units:
        c = KIND_COLOR.get(kind, (80, 80, 80))
        cv2.rectangle(canvas, (round(b[0] * W), round(b[1] * H)), (round(b[2] * W), round(b[3] * H)), c, 2)
        _label(canvas, uid, (round(b[0] * W), round(b[1] * H)), c, 0.55, 1)
    if not ruler:
        return canvas
    m = 34
    out = np.full((H + 2 * m, W + 2 * m, 3), 255, np.uint8)
    out[m : m + H, m : m + W] = canvas
    for k in range(11):
        t = k / 10
        x, y = m + round(t * W), m + round(t * H)
        cv2.line(out, (x, m - 8), (x, m), (0, 0, 0), 1)
        cv2.line(out, (m - 8, y), (m, y), (0, 0, 0), 1)
        cv2.putText(out, f"{t:.1f}", (x - 10, m - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(out, f"{t:.1f}", (1, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)
    return out


def panel_crop(img: np.ndarray, panel: dict, units: list[tuple[str, str, list]], long_side: int = 1024) -> np.ndarray:
    H, W = img.shape[:2]
    x, y, w, h = panel["bbox"]
    x0, y0, x1, y1 = max(0, round(x * W)), max(0, round(y * H)), min(W, round((x + w) * W)), min(H, round((y + h) * H))
    crop = img[y0:y1, x0:x1]
    k = long_side / max(crop.shape[:2])
    crop = cv2.resize(crop, (round(crop.shape[1] * k), round(crop.shape[0] * k)), interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)
    for uid, kind, b in units:  # unit tags drawn on the crop, outline only
        bx0, by0, bx1, by1 = (b[0] * W - x0) * k, (b[1] * H - y0) * k, (b[2] * W - x0) * k, (b[3] * H - y0) * k
        if bx1 < 0 or by1 < 0 or bx0 > crop.shape[1] or by0 > crop.shape[0]:
            continue
        c = KIND_COLOR.get(kind, (80, 80, 80))
        cv2.rectangle(crop, (round(bx0), round(by0)), (round(bx1), round(by1)), c, 2)
        _label(crop, uid, (round(bx0), round(by0)), c, 0.7, 2)
    return crop


def write_inputs(img: np.ndarray, panels: list[dict], units: list[tuple[str, str, list]], out: Path, tag: str) -> dict:
    """Write clean page, overlay and crops under `out`; returns {"clean": path, "overlay": path, "crops": {panel id: path}}."""
    out.mkdir(parents=True, exist_ok=True)
    clean, _ = _fit(img)
    paths = dict(clean=out / f"{tag}-clean.jpg", overlay=out / f"{tag}-overlay.jpg", crops={})
    cv2.imwrite(str(paths["clean"]), clean, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(paths["overlay"]), overlay_image(img, panels, units), [cv2.IMWRITE_JPEG_QUALITY, 92])
    for p in panels:
        f = out / f"{tag}-crop-{p['id']}.jpg"
        cv2.imwrite(str(f), panel_crop(img, p, units), [cv2.IMWRITE_JPEG_QUALITY, 92])
        paths["crops"][p["id"]] = f
    return paths
