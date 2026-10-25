"""Panel detection vs the reference rects: mean IoU of matched panels, recall, precision (plan gate 1.1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

from ugoku.pipeline.panels import detect_panels

from .common import load_eval
from .metrics import match_rects, panel_scores


def run(cfg, ref, draw: bool = True) -> list[dict]:
    rows = []
    odir = Path(cfg["out"]) / "panels"
    odir.mkdir(parents=True, exist_ok=True)
    for pg in ref["pages"]:
        pid = pg["page"]
        img = cv2.imread(str(cfg["pages"] / f"{pid}.png"))
        pred = detect_panels(img)
        refs = [p["rect"] for p in pg["panels"]]
        s = panel_scores([p.bbox for p in pred], refs)
        s["page"] = pid
        m = match_rects([p.bbox for p in pred], refs, 0.5)
        s["ious"] = {pg["panels"][j]["id"]: round(v, 3) for _, j, v in m}
        s["missed"] = [pg["panels"][j]["id"] for j in range(len(refs)) if j not in {x[1] for x in m}]
        rows.append(s)
        if draw:
            H, W = img.shape[:2]
            for p in pred:
                x, y, w, h = p.bbox
                cv2.rectangle(img, (round(x * W), round(y * H)), (round((x + w) * W), round((y + h) * H)), (0, 0, 255), 4)
            for r in refs:
                x, y, w, h = r
                cv2.rectangle(img, (round(x * W), round(y * H)), (round((x + w) * W), round((y + h) * H)), (0, 160, 0), 2)
            cv2.imwrite(str(odir / f"{pid}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return rows


def summarize(rows) -> dict:
    tm = sum(r["matched"] for r in rows)
    ious = [v for r in rows for v in r["ious"].values()]
    return dict(mean_iou=float(np.mean(ious)), recall=tm / sum(r["n_ref"] for r in rows), precision=tm / sum(r["n_pred"] for r in rows),
                pages_below_0_7=[r["page"] for r in rows if r["ious"] and np.mean(list(r["ious"].values())) < 0.7 or r["missed"]])


def main() -> int:
    cfg = load_eval()
    ref = json.load(open(Path(cfg["out"]) / "ref_direction.json"))
    rows = run(cfg, ref)
    (Path(cfg["out"]) / "panels_eval.json").write_text(json.dumps(rows, indent=1))
    print(json.dumps(summarize(rows), indent=1))
    for r in rows:
        print(r["page"], r["n_pred"], r["n_ref"], f"iou {np.mean(list(r['ious'].values())) if r['ious'] else 0:.3f}", "missed", r["missed"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
