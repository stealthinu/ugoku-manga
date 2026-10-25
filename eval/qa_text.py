"""Baseline text-leak flag rate on the reference clips (`python -m eval.qa_text`). Numbers and ids only are written."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

from ugoku.pipeline.qa import qa_text, read_frames

from .common import load_eval


def exclusion(work: Path, page: str, rect) -> np.ndarray:
    x0, y0, x1, y1 = rect
    ex = np.zeros((y1 - y0, x1 - x0), np.uint8)
    for k in ("hide", "flat"):
        p = work / f"{k}_{page}.png"
        if p.exists():
            ex |= (cv2.imread(str(p), 0)[y0:y1, x0:x1] > 0).astype(np.uint8)
    return ex


def main() -> int:
    cfg = load_eval()
    import os

    os.environ.setdefault("UGOKU_MODEL_DIR", str(cfg["models"]))
    gal = Path(cfg["gallery_v5"])
    data = json.load(open(gal / "data.json"))
    out_path = Path(cfg["out"]) / "qa_text_v5.json"
    res = json.load(open(out_path)) if out_path.exists() else {}
    for pg in data["pages"]:
        for q in pg["panels"]:
            if not q.get("src_rect") or not q.get("mp4") or q["id"] in res:
                continue
            fr = read_frames(str(gal / q["mp4"]))
            res[q["id"]] = qa_text(fr, exclusion(Path(cfg["work_v5"]), pg["id"], q["src_rect"]))
            print(q["id"], res[q["id"]], flush=True)
            out_path.write_text(json.dumps(res, indent=1))
    fl = [k for k, v in res.items() if v["flag"]]
    print(json.dumps(dict(clips=len(res), flagged=len(fl), rate=round(len(fl) / len(res), 4), ids=fl), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
