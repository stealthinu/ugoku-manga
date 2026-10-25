"""Golden check on a sample work: detectors and ordering vs the generator's exact truth (`python -m eval.golden samples/<work>...`)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

from ugoku.pipeline.order import assign_units, band_order, order_panels
from ugoku.pipeline.panels import detect_panels
from ugoku.pipeline.truth import load_truth
from ugoku.pipeline.units import analyze_units

from .metrics import box_overlap, kendall_tau, match_rects


def evaluate_work(work_dir: Path) -> dict:
    t = load_truth(work_dir / "truth.json")
    rtl = t["reading"] == "rtl"
    ious, n_match, n_pred, n_ref = [], 0, 0, 0
    panel_exact, order_exact, ub_match, ub_ref, ub_pred = 0, 0, 0, 0, 0
    kinds = {k: [0, 0] for k in ("bubble", "sfx", "manpu")}
    taus, pages = [], 0
    for pg in t["pages"]:
        img = cv2.imread(str(work_dir / pg["image"]))
        H, W = img.shape[:2]
        pans = detect_panels(img)
        o = order_panels([p.bbox for p in pans], "rtl" if rtl else "ltr")
        pred = [pans[i] for i in o]
        ref = [[min(x for x, _ in p["poly"]) / W, min(y for _, y in p["poly"]) / H, (max(x for x, _ in p["poly"]) - min(x for x, _ in p["poly"])) / W,
                (max(y for _, y in p["poly"]) - min(y for _, y in p["poly"])) / H] for p in pg["panels"]]
        m = match_rects([p.bbox for p in pred], ref, 0.5)
        ious += [v for _, _, v in m]
        n_match += len(m)
        n_pred += len(pred)
        n_ref += len(ref)
        pages += 1
        panel_exact += int(len(m) == len(ref) == len(pred) and all(i == j for i, j, _ in m))
        us = analyze_units(img)
        boxes = [u.box for u in us.units]
        tb = {u["id"]: [u["bbox"][0] / W, u["bbox"][1] / H, u["bbox"][2] / W, u["bbox"][3] / H] for u in pg["units"]}
        hit = {}
        for u in pg["units"]:
            best = max(range(len(boxes)), key=lambda i: box_overlap(boxes[i], tb[u["id"]]), default=None)
            kinds[u["kind"]][1] += 1
            if best is not None and box_overlap(boxes[best], tb[u["id"]]) >= 0.5:
                kinds[u["kind"]][0] += 1
                hit[u["id"]] = best
        ub_pred += len(boxes)
        # reading order of the matched bubbles: panels first, then bands inside a panel
        bub = [u for u in pg["unit_order"] if u in hit]
        ub_ref += len(pg["unit_order"])
        ub_match += len(bub)
        if len(bub) == len(pg["unit_order"]) and bub:
            panel_boxes = [dict(id=f"P{i}", bbox=p.bbox, poly=p.poly) for i, p in enumerate(pred)]
            asg = assign_units(us, panel_boxes)
            seq = []
            for i, p in enumerate(panel_boxes):
                ids = [uid for uid in bub if asg.get(us.units[hit[uid]].id) == p["id"]]
                oo = band_order([us.units[hit[u]].box for u in ids], "rtl" if rtl else "ltr")
                seq += [ids[k] for k in oo]
            order_exact += int(seq == bub)
            taus.append(kendall_tau([bub.index(u) for u in seq], list(range(len(seq)))) if len(seq) > 1 else 1.0)
    return dict(pages=pages, panel_mean_iou=round(float(np.mean(ious)), 3) if ious else 0, panel_recall=round(n_match / max(1, n_ref), 3), panel_precision=round(n_match / max(1, n_pred), 3),
                panel_order_exact=round(panel_exact / pages, 3), unit_recall={k: round(a / b, 3) if b else None for k, (a, b) in kinds.items()},
                bubble_order_exact=round(order_exact / pages, 3), bubble_order_tau=round(float(np.mean(taus)), 3) if taus else None)


def main() -> int:
    res = {}
    for d in sys.argv[1:]:
        res[Path(d).name] = evaluate_work(Path(d))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
