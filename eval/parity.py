"""P1 parity check: run the CPU stage on the private pages with the converted reference direction and compare with the reference gallery.

Reports per page: mean absolute pixel difference of the base page, IoU of each layer alpha mask (>=128), IoU of the hide/flat masks.
Gate: mean pixel diff < 1.0 and layer mask IoU >= 0.98.
"""
from __future__ import annotations

import json
import os
import sys
import time
from multiprocessing import get_context
from pathlib import Path

import numpy as np

from .common import load_eval


def iou(a: np.ndarray, b: np.ndarray) -> float:
    u = (a | b).sum()
    return 1.0 if u == 0 else float((a & b).sum() / u)


def _canvas_mask(rgba: np.ndarray, rect, W, H) -> np.ndarray:
    m = np.zeros((H, W), bool)
    x0, y0 = round(rect[0] * W), round(rect[1] * H)
    h, w = rgba.shape[:2]
    m[y0 : y0 + h, x0 : x0 + w] = rgba[:, :, 3] >= 128
    return m


def _one(args):
    pg, cfg = args
    import cv2

    cv2.setNumThreads(1)
    from ugoku.pipeline.stage import prepare_page

    pid = pg["page"]
    t = time.time()
    img = cv2.imread(str(cfg["pages"] / f"{pid}.png"))
    entry, rep, stage, files = prepare_page(img, pg, "eval")
    H, W = img.shape[:2]
    res = dict(page=pid, secs=round(time.time() - t, 1), keep=bool(rep.get("keep")), warn=len(rep["warn"]))
    if res["keep"]:
        return res
    gal = Path(cfg["gallery_v5"])
    ref_base = cv2.imread(str(gal / "pages" / f"{pid}.png"))
    res["base_diff"] = float(np.abs(files[f"pages/{pid}.png"].astype(np.int16) - ref_base.astype(np.int16)).mean())
    res["base_diff_max_px"] = int((np.abs(files[f"pages/{pid}.png"].astype(np.int16) - ref_base.astype(np.int16)).max(axis=2) > 24).sum())
    ref_pg = next(p for p in json.load(open(gal / "data.json"))["pages"] if p["id"] == pid)
    ours = {lay["id"]: lay for lay in entry["layers"]}
    ious = {}
    for rl in ref_pg["layers"]:
        lid = rl["id"]
        if lid not in ours:
            ious[lid] = 0.0
            continue
        a = _canvas_mask(cv2.imread(str(gal / rl["src"]), cv2.IMREAD_UNCHANGED), rl["rect"], W, H)
        b = _canvas_mask(files[ours[lid]["src"]], ours[lid]["rect"], W, H)
        ious[lid] = iou(a, b)
    res["layers_ref"] = len(ref_pg["layers"])
    res["layers_ours"] = len(entry["layers"])
    res["layer_iou"] = ious
    res["kinds_match"] = all(ours[k]["kind"] == r["kind"] for r in ref_pg["layers"] for k in [r["id"]] if k in ours)
    wk = cfg.get("work_v5")
    if wk and (Path(wk) / f"hide_{pid}.png").exists():
        for nm in ("hide", "flat"):
            r = cv2.imread(str(Path(wk) / f"{nm}_{pid}.png"), 0) > 0
            res[f"{nm}_iou"] = iou(r, files[f"work/{nm}_{pid}.png"] > 0)
    res["stage_ids_match"] = sorted(s["id"] for s in stage) == sorted(q["id"] for q in ref_pg["panels"] if q.get("mp4"))
    return res


def main() -> int:
    cfg = load_eval()
    if "models" in cfg:
        os.environ["UGOKU_MODEL_DIR"] = str(cfg["models"])
    out = Path(cfg["out"])
    ref = json.load(open(out / "ref_direction.json"))
    procs = int(os.environ.get("UGOKU_EVAL_PROCS", "3"))
    with get_context("spawn").Pool(procs) as pool:
        rows = pool.map(_one, [(pg, cfg) for pg in ref["pages"]], chunksize=1)
    rows.sort(key=lambda r: r["page"])
    (out / "parity.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    ok = [r for r in rows if not r["keep"]]
    bd = [r["base_diff"] for r in ok]
    li = [v for r in ok for v in r["layer_iou"].values()]
    print(f"pages compared {len(ok)} (keep/skipped {len(rows) - len(ok)})")
    print(f"base mean abs diff: mean {np.mean(bd):.3f} max {np.max(bd):.3f}; pages >=1.0: {sum(d >= 1.0 for d in bd)}")
    share = np.mean([v >= 0.98 for v in li])
    print(f"layers: ref {sum(r['layers_ref'] for r in ok)} ours {sum(r['layers_ours'] for r in ok)}; iou mean {np.mean(li):.4f} min {np.min(li):.3f} share>=0.98 {share:.3f}")
    for nm in ("hide", "flat"):
        v = [r[f"{nm}_iou"] for r in ok if f"{nm}_iou" in r]
        if v:
            print(f"{nm} mask iou: mean {np.mean(v):.4f} min {np.min(v):.3f}")
    print("stage ids match:", sum(r["stage_ids_match"] for r in ok), "/", len(ok), "; kinds match:", sum(r["kinds_match"] for r in ok), "/", len(ok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
