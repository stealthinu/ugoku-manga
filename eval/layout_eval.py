"""Units and reading order vs the reference gallery: unit recall/precision per kind (IoU>=0.5), Kendall tau and exact page-sequence match.

Writes only numbers and ids (no text). Unit analyses are cached under `out/units/` (the detector is the slow part).
"""
from __future__ import annotations

import json
import os
import sys
from multiprocessing import get_context
from pathlib import Path

import numpy as np

from ugoku.pipeline.order import assign_units, band_order, order_panels
from ugoku.pipeline.units import UnitSet, analyze_units

from .common import load_eval
from .metrics import box_overlap, kendall_tau, match_rects


def units_for(cfg, pid: str) -> UnitSet:
    import cv2

    d = Path(cfg["out"]) / "units"
    d.mkdir(parents=True, exist_ok=True)
    f = d / pid
    if f.with_suffix(".npz").exists():
        return UnitSet.load(f)
    cv2.setNumThreads(1)
    us = analyze_units(cv2.imread(str(cfg["pages"] / f"{pid}.png")))
    us.save(f)
    return us


def _warm(args):
    cfg, pid = args
    os.environ["UGOKU_MODEL_DIR"] = str(cfg["models"])
    units_for(cfg, pid)
    return pid


def warm_units(cfg, pids, procs: int = 3) -> None:
    with get_context("spawn").Pool(procs) as pool:
        pool.map(_warm, [(cfg, p) for p in pids], chunksize=1)


def reading_sequence(panels: list[dict], us: UnitSet, reading: str = "rtl"):
    """(panel ids in order, unit ids of dialogue/free units in page reading order, unit->panel)."""
    po = order_panels([p["bbox"] for p in panels], reading)
    ordered = [panels[i] for i in po]
    a = assign_units(us, ordered)
    seq = []
    for p in ordered:
        mine = [u for u in us.units if a[u.id] == p["id"] and u.kind != "sfx"]
        seq += [mine[i].id for i in band_order([u.box for u in mine], reading)]
    return [p["id"] for p in ordered], seq, a


def evaluate_page(cfg, pg, gp, panels) -> dict:
    us = units_for(cfg, pg["page"])
    pids, seq, assign = reading_sequence(panels, us)
    res = dict(page=pg["page"])
    # panel order: matched panels, Kendall tau and exact sequence of the matched subset
    m = match_rects([p["bbox"] for p in panels], [p["rect"] for p in pg["panels"]], 0.5)
    ref_rank = {pg["panels"][j]["id"]: pg["panels"][j].get("order", j) for _, j in [(i, j) for i, j, _ in m]}
    ours_rank = {panels[i]["id"]: pids.index(panels[i]["id"]) for i, _, _ in m}
    pm = {panels[i]["id"]: pg["panels"][j]["id"] for i, j, _ in m}
    ks = [k for k in pm]
    res["panel_tau"] = kendall_tau([ours_rank[k] for k in ks], [ref_rank[pm[k]] for k in ks]) if ks else 1.0
    res["panel_exact"] = [pm[p] for p in pids if p in pm] == sorted(pm.values(), key=lambda v: ref_rank[v])  # order of the matched panels
    # units: overlap-based (intersection / smaller area >= 0.5), like the stage matching; strict IoU is reported as well
    ulist = us.units
    res["units"] = {}
    cls = {"bubble": ("balloon", "free"), "sfx": ("sfx",), "manpu": ("sfx",)}
    best_for_layer: dict[int, tuple[float, str]] = {}
    for rk in ("bubble", "sfx", "manpu"):
        refl = [lay for lay in gp["layers"] if lay["kind"] == rk and lay.get("order", 0) < 90]  # order >= 90: text the direction did not list
        cand = [u for u in ulist if u.kind in cls[rk]]
        hit = iou_hit = 0
        for lay in refl:
            r = lay["rect"]
            rr = [r[0], r[1], r[0] + r[2], r[1] + r[3]]
            ov = [(box_overlap(u.box, rr), u) for u in cand]
            ov = [x for x in ov if x[0] >= 0.5]
            if ov:
                hit += 1
                if rk == "bubble":
                    best_for_layer[lay["order"]] = max(ov, key=lambda x: x[0])[1].id
        iou_hit = len(match_rects([u.bbox() for u in cand], [lay["rect"] for lay in refl], 0.5))
        res["units"][rk] = dict(ref=len(refl), matched=hit, matched_iou=iou_hit)
    refs_all = [lay for lay in gp["layers"]]
    tp = 0
    for u in ulist:
        for lay in refs_all:
            r = lay["rect"]
            if box_overlap(u.box, [r[0], r[1], r[0] + r[2], r[1] + r[3]]) >= 0.5:
                tp += 1
                break
    res["units"]["detected"] = len(ulist)
    res["units"]["detected_in_ref"] = tp
    rank = {u: i for i, u in enumerate(seq)}
    pairs = [(rank[uid], o) for o, uid in best_for_layer.items() if uid in rank]
    if len(pairs) >= 2:
        res["unit_tau"] = kendall_tau([a for a, _ in pairs], [b for _, b in pairs])
        res["unit_exact"] = res["unit_tau"] >= 0.9999
        res["unit_n"] = len(pairs)
    return res


def summarize(rows) -> dict:
    s = {}
    for k in ("bubble", "sfx", "manpu"):
        r, m = sum(x["units"][k]["ref"] for x in rows), sum(x["units"][k]["matched"] for x in rows)
        s[f"{k}_recall"] = m / r if r else None
    s["bubble_recall_iou"] = sum(x["units"]["bubble"]["matched_iou"] for x in rows) / sum(x["units"]["bubble"]["ref"] for x in rows)
    s["unit_precision"] = sum(x["units"]["detected_in_ref"] for x in rows) / sum(x["units"]["detected"] for x in rows)
    s["sfx_manpu_recall"] = (sum(x["units"]["sfx"]["matched"] + x["units"]["manpu"]["matched"] for x in rows)) / max(1, sum(x["units"]["sfx"]["ref"] + x["units"]["manpu"]["ref"] for x in rows))
    ut = [x["unit_tau"] for x in rows if "unit_tau" in x]
    s["unit_tau_mean"] = float(np.mean(ut)) if ut else None
    s["unit_page_exact"] = float(np.mean([x["unit_exact"] for x in rows if "unit_exact" in x])) if ut else None
    s["panel_tau_mean"] = float(np.mean([x["panel_tau"] for x in rows]))
    s["panel_page_exact"] = float(np.mean([x["panel_exact"] for x in rows]))
    return s


def main() -> int:
    cfg = load_eval()
    os.environ["UGOKU_MODEL_DIR"] = str(cfg["models"])
    import cv2

    from ugoku.pipeline.panels import detect_panels

    ref = json.load(open(Path(cfg["out"]) / "ref_direction.json"))
    gal = {p["id"]: p for p in json.load(open(Path(cfg["gallery_v5"]) / "data.json"))["pages"]}
    warm_units(cfg, [p["page"] for p in ref["pages"]])
    rows = []
    for pg in ref["pages"]:
        det = detect_panels(cv2.imread(str(cfg["pages"] / f"{pg['page']}.png")))
        panels = [dict(id=f"P{i + 1}", bbox=p.bbox, poly=p.poly) for i, p in enumerate(det)]
        rows.append(evaluate_page(cfg, pg, gal[pg["page"]], panels))
    (Path(cfg["out"]) / "layout_eval.json").write_text(json.dumps(rows, indent=1))
    print(json.dumps(summarize(rows), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
