"""Evaluate the sample galleries after a GPU run (`python -m eval.samples_round R05 <gallery-dir>...`): score5 per animated panel, qa_text, LLM judge and direction semantics.

Numbers and ids go to `<out>/samples-<tag>.json`; the committed round report keeps numbers only. Judge calls go one at a time through the `claude_cli` provider (cached).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

from .common import load_eval
from .judge import RUBRIC, judge, semantics
from .score5 import clip_metrics, read_gray, score


def eval_work(gal: Path, prov, work: Path) -> list[dict]:
    from ugoku.pipeline.qa import qa_text, read_frames

    from .qa_text import exclusion

    data = json.load(open(gal / "data.json"))
    spec = {p["id"]: p for p in json.load(open(gal / "stage" / "spec.json"))["panels"]}
    rows = []
    for pg in data["pages"]:
        for q in pg["panels"]:
            if q.get("static") or not q.get("mp4"):
                continue
            vid = str(gal / q["mp4"])
            src = cv2.imread(str(gal / "stage" / spec[q["id"]]["file"]))
            met = clip_metrics(read_gray(vid), cv2.cvtColor(src, cv2.COLOR_BGR2GRAY).astype(np.float32))
            row = dict(id=q["id"], work=gal.name, score=score(met), motion=met["motion"], sharp_min=met["sharp_min"], flick=met["flick"], mode=q.get("mode"))
            row["qa"] = qa_text(read_frames(vid), exclusion(gal / "work", pg["id"], q["src_rect"]))
            if prov:
                row["judge"] = judge(prov, vid, src, q["action"], work / "judge", f"{gal.name}-{q['id']}")
                row["sem"] = semantics(prov, vid, src, q["action"], work / "sem", f"{gal.name}-{q['id']}")
            rows.append(row)
            print(row["work"], row["id"], row["score"], row["qa"]["flag"], row.get("sem", {}).get("direction_ok"), flush=True)
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("galleries", nargs="+")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_eval()
    os.environ["UGOKU_MODEL_DIR"] = str(cfg["models"])
    from ugoku.backends.llm import CachedProvider, make_provider

    out = Path(cfg["out"])
    prov = None if a.no_judge else CachedProvider(make_provider("claude_cli", model=a.model), out / "llm-cache")
    rows = []
    for g in a.galleries:
        rows += eval_work(Path(g), prov, out / f"samples-{a.tag}")
    n = len(rows)
    summ = dict(tag=a.tag, n=n, score_mean=round(float(np.mean([r["score"] for r in rows])), 3), ge4=sum(r["score"] >= 4 for r in rows), le2=sum(r["score"] <= 2 for r in rows),
                qa_flagged=sum(r["qa"]["flag"] for r in rows), qa_rate=round(sum(r["qa"]["flag"] for r in rows) / n, 4))
    if prov:
        summ["judge_mean"] = round(float(np.mean([r["judge"]["overall"] for r in rows])), 3)
        summ["judge_items"] = {k: round(float(np.mean([r["judge"][k] for r in rows])), 2) for k in RUBRIC}
        summ["sem_direction_bad"] = [r["id"] for r in rows if not r["sem"]["direction_ok"]]
        summ["sem_reverse"] = [r["id"] for r in rows if r["sem"]["reverse_motion"]]
        summ["sem_added_text"] = [r["id"] for r in rows if r["sem"]["added_text_or_sfx"]]
        summ["sem_no_motion"] = [r["id"] for r in rows if not r["sem"]["motion_visible"]]
    (out / f"samples-{a.tag}.json").write_text(json.dumps(dict(summary=summ, rows=rows), indent=1))
    print(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
