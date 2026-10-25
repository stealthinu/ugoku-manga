"""Text detection: pixel-level text probability (comic-text-detector ONNX) and bubble/text boxes (RT-DETR ONNX).

Origin: the text-detector helper of the prototype. The GPL-licensed segmentation model is an optional
runtime download and is only touched through this module, so it can be replaced.
"""
from __future__ import annotations

import cv2
import numpy as np
import onnxruntime as ort

from ...config import load
from ...models import model_path

_sessions: dict[str, ort.InferenceSession] = {}


def session(name: str) -> ort.InferenceSession:
    if name not in _sessions:
        s = load()
        o = ort.SessionOptions()
        o.intra_op_num_threads = s.threads
        _sessions[name] = ort.InferenceSession(str(model_path(name, s)), o, providers=["CPUExecutionProvider"])
    return _sessions[name]


def text_probability(img: np.ndarray) -> np.ndarray:
    """Per-pixel text probability (H, W) float32 for a BGR image. Letterboxed to 1024 and centred."""
    H, W = img.shape[:2]
    r = 1024 / max(H, W)
    nh, nw = round(H * r), round(W * r)
    im = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    pad = np.full((1024, 1024, 3), 114, np.uint8)
    dy, dx = (1024 - nh) // 2, (1024 - nw) // 2
    pad[dy : dy + nh, dx : dx + nw] = im
    x = pad[:, :, ::-1].astype(np.float32).transpose(2, 0, 1)[None] / 255
    _blk, seg, _det = session("ctd").run(None, {"images": x})
    s = seg[0, 0][dy : dy + nh, dx : dx + nw]
    return cv2.resize(s, (W, H), interpolation=cv2.INTER_LINEAR)


def bubbles(img: np.ndarray, thr: float = 0.4) -> list[tuple[int, list[float], float]]:
    """Detections as (label, [x0, y0, x1, y1], score). Labels: 0 = bubble, 1/2 = free text."""
    H, W = img.shape[:2]
    im = cv2.resize(img, (640, 640))[:, :, ::-1].astype(np.float32).transpose(2, 0, 1)[None] / 255
    lab, box, sc = session("bubble").run(None, {"images": im, "orig_target_sizes": np.array([[W, H]], np.int64)})
    return [(int(l), [float(v) for v in b], float(s)) for l, b, s in zip(lab[0], box[0], sc[0]) if s >= thr]
