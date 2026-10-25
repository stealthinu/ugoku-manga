"""Motion metrics and the 1-5 score of the earlier prototype, re-implemented (the score is metric-only: no one looked at the videos to score them).

Origin: the prototype's per-clip metric function (changed-area, flicker, sharpness, specks) and its score step.
Self-test (`python -m eval.score5`): recompute the metrics from the reference videos and check that the formula reproduces the reference scores
(the one manually capped clip excepted).
"""
from __future__ import annotations

import json
import sys
from multiprocessing import get_context
from pathlib import Path

import cv2
import numpy as np

from .common import load_eval


def read_gray(path: str) -> np.ndarray:
    c = cv2.VideoCapture(path)
    fr = []
    while True:
        ok, f = c.read()
        if not ok:
            break
        fr.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32))
    return np.stack(fr)


def clip_metrics(out: np.ndarray, orig: np.ndarray) -> dict:
    """out: frames (n, h, w) gray float32; orig: the source panel (h, w). Same definitions as the prototype."""
    d = np.abs(out - orig[None])
    n = len(out)
    un = d.max(axis=0) > 6
    m = cv2.dilate(un.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    acc = float(np.abs(out[2:] - 2 * out[1:-1] + out[:-2])[:, m].mean()) if m.any() else 0.0
    _, _, st, _ = cv2.connectedComponentsWithStats(un.astype(np.uint8), connectivity=8)
    specks = int((st[1:, 4] < 12).sum())

    def lap(g):
        return cv2.Laplacian(g.astype(np.float32), cv2.CV_32F).var()

    sh = []
    if m.any():
        ys, xs = np.where(m)
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        lo = lap(orig[y0:y1, x0:x1]) + 1e-6
        for t in range(0, n, 6):
            sh.append(lap(out[t][y0:y1, x0:x1]) / lo)
    chg = (d > 50).mean(axis=(1, 2)).max()
    return dict(area=round(float(un.mean() * 100), 1), peak50=round(float(chg * 100), 2), flick=round(acc, 3), specks=specks, tail=round(float(d[-1].mean()), 2),
                sharp_min=round(float(min(sh)) if sh else 1, 2), mad=round(float(d.mean()), 3), p95=round(float(np.percentile(d.max(axis=0), 99)), 1),
                n=n, d0=round(float(np.abs(out[0] - orig).mean()), 2), motion=round(float(np.abs(np.diff(out, axis=0)).mean()), 3))


def score(m: dict) -> int:
    """1-5 from motion strength, sharpness and flicker (the prototype's rule, without its manual cap)."""
    mo, sh, fl = m["motion"], m["sharp_min"], m["flick"]
    b = 1 if mo < 0.5 else 2 if mo < 1.5 else 3 if mo < 3 else 4
    if mo >= 6 and sh >= 0.5 and fl < 20:
        b = 5
    return int(max(1, b - (sh < 0.3) - (fl > 25)))


def _one(args):
    cid, vid, page_img, rect = args
    cv2.setNumThreads(1)
    out = read_gray(vid)
    pg = cv2.imread(page_img, 0).astype(np.float32)
    x0, y0, x1, y1 = rect
    return cid, clip_metrics(out, pg[y0:y1, x0:x1])


def main() -> int:
    cfg = load_eval()
    gal = Path(cfg["gallery_v5"])
    data = json.load(open(gal / "data.json"))
    jobs = [(q["id"], str(gal / "media" / f"{q['id']}.mp4"), str(gal / "pages" / f"{p['id']}.png"), q["src_rect"]) for p in data["pages"] for q in p["panels"] if q.get("src_rect")]
    with get_context("spawn").Pool(3) as pool:
        ours = dict(pool.map(_one, jobs, chunksize=1))
    out = Path(cfg["out"])
    (out / "score5_metrics.json").write_text(json.dumps(ours, indent=1))
    res = dict(n=len(ours))
    if cfg.get("metrics_v5") and Path(cfg["metrics_v5"]).exists():
        ref_m = json.load(open(cfg["metrics_v5"]))
        res["metric_max_abs_diff"] = {k: max(abs(ours[c][k] - ref_m[c][k]) for c in ref_m if c in ours) for k in ("motion", "sharp_min", "flick", "area", "mad")}
    if cfg.get("scores_v5") and Path(cfg["scores_v5"]).exists():
        ref_s = json.load(open(cfg["scores_v5"]))
        mism = [c for c in ref_s if c in ours and score(ours[c]) != ref_s[c]]
        res["score_reproduced"] = f"{len(ref_s) - len(mism)}/{len(ref_s)}"
        res["score_mismatch"] = [(c, score(ours[c]), ref_s[c]) for c in mism]
        res["mean_ours_formula"] = round(float(np.mean([score(m) for m in ours.values()])), 3)
        res["mean_ref"] = round(float(np.mean(list(ref_s.values()))), 3)
        res["ge4_ref"] = sum(v >= 4 for v in ref_s.values())
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
