"""Score a generated direction against the reference: panels, units, order, h3 selection and mode agreement, validity (numbers and ids only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from .common import load_eval
from .metrics import box_overlap, cohen_kappa, kendall_tau, match_rects, panel_scores


def _xyxy(r):
    return [r[0], r[1], r[0] + r[2], r[1] + r[3]]


def eval_pages(gen: dict, ref: dict, gal: dict) -> list[dict]:
    rows = []
    gpages = {p["page"]: p for p in gen["pages"]}
    for rp in ref["pages"]:
        pid = rp["page"]
        g = gpages.get(pid)
        if g is None:
            rows.append(dict(page=pid, missing=True))
            continue
        row = dict(page=pid)
        row["panels"] = panel_scores([p["rect"] for p in g["panels"]], [p["rect"] for p in rp["panels"]])
        m = match_rects([p["rect"] for p in g["panels"]], [p["rect"] for p in rp["panels"]], 0.5)
        sel = [(g["panels"][i]["type"] == "h3_full", rp["panels"][j]["type"] == "h3_full") for i, j, _ in m if rp["panels"][j]["type"] != "keep"]
        row["sel"] = sel
        row["mode"] = [(g["panels"][i].get("mode"), rp["panels"][j].get("mode")) for i, j, _ in m if g["panels"][i]["type"] == "h3_full" and rp["panels"][j]["type"] == "h3_full"]
        row["mag"] = [(g["panels"][i].get("magnitude"), rp["panels"][j].get("magnitude")) for i, j, _ in m if g["panels"][i]["type"] == "h3_full" and rp["panels"][j]["type"] == "h3_full"]
        # panel order on the matched panels
        ours_rank = [g["panels"][i]["order"] for i, _, _ in m]
        ref_rank = [rp["panels"][j].get("order", j) for _, j, _ in m]
        row["panel_tau"] = kendall_tau(ours_rank, ref_rank)
        row["panel_exact"] = [x for _, x in sorted(zip(ours_rank, ref_rank))] == sorted(ref_rank)
        # units against the reference layers (pixel layers of the reference gallery)
        layers = [lay for lay in gal[pid]["layers"] if lay.get("order", 0) < 90]
        ours = [(b["rect"], "bubble", b["order"]) for b in g["bubbles"]] + [(f["rect"], f["kind"], 0) for f in g["fx"]]
        row["units"] = {}
        pairs = []
        for kinds, name in ((("bubble",), "bubble"), (("sfx", "manpu", "screen"), "fx")):
            refl = [lay for lay in layers if lay["kind"] in kinds]
            cand = [o for o in ours if (o[1] == "bubble") == (name == "bubble")]
            hit = 0
            for lay in refl:
                ov = [(box_overlap(_xyxy(c[0]), _xyxy(lay["rect"])), c) for c in cand]
                ov = [x for x in ov if x[0] >= 0.5]
                if ov:
                    hit += 1
                    if name == "bubble":
                        pairs.append((max(ov, key=lambda x: x[0])[1][2], lay["order"]))
            prec = sum(any(box_overlap(_xyxy(c[0]), _xyxy(lay["rect"])) >= 0.5 for lay in refl) for c in cand)
            row["units"][name] = dict(ref=len(refl), hit=hit, pred=len(cand), pred_hit=prec)
        row["unit_tau"] = kendall_tau([a for a, _ in pairs], [b for _, b in pairs]) if len(pairs) >= 2 else None
        rows.append(row)
    return rows


def summarize(rows: list[dict], reports: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("missing")]
    s: dict = {}
    tm = sum(r["panels"]["matched"] for r in ok)
    s["panel_recall"] = tm / sum(r["panels"]["n_ref"] for r in ok)
    s["panel_precision"] = tm / sum(r["panels"]["n_pred"] for r in ok)
    s["panel_mean_iou"] = float(np.average([r["panels"]["mean_iou"] for r in ok], weights=[max(1, r["panels"]["matched"]) for r in ok]))
    for k, nm in (("bubble", "bubble"), ("fx", "sfx_manpu")):
        s[f"{nm}_recall"] = sum(r["units"][k]["hit"] for r in ok) / max(1, sum(r["units"][k]["ref"] for r in ok))
        s[f"{nm}_precision"] = sum(r["units"][k]["pred_hit"] for r in ok) / max(1, sum(r["units"][k]["pred"] for r in ok))
    ut = [r["unit_tau"] for r in ok if r.get("unit_tau") is not None]
    s["unit_tau_mean"] = float(np.mean(ut))
    s["unit_page_exact"] = float(np.mean([t > 0.9999 for t in ut]))
    s["panel_tau_mean"] = float(np.mean([r["panel_tau"] for r in ok]))
    s["panel_page_exact"] = float(np.mean([r["panel_exact"] for r in ok]))
    sel = [x for r in ok for x in r["sel"]]
    a, b = [x[0] for x in sel], [x[1] for x in sel]
    s["h3_agree"] = float(np.mean([x == y for x, y in sel]))
    s["h3_kappa"] = cohen_kappa(a, b)
    s["h3_ours_share"], s["h3_ref_share"] = float(np.mean(a)), float(np.mean(b))
    md = [x for r in ok for x in r["mode"]]
    s["mode_agree"] = float(np.mean([x == y for x, y in md])) if md else None
    mg = [x for r in ok for x in r["mag"]]
    s["magnitude_agree"] = float(np.mean([x == y for x, y in mg])) if mg else None
    if reports:
        s["schema_valid_no_degrade"] = float(np.mean([bool(r.get("valid_without_degrade")) for r in reports]))
        s["schema_valid"] = float(np.mean([bool(r.get("valid")) for r in reports]))
        s["pages_degraded"] = [r["page"] for r in reports if r.get("degraded")]
        s["pages_failed"] = [r["page"] for r in reports if r.get("error")]
        s["repairs"] = sum(r.get("repairs", 0) for r in reports)
        s["critic_rounds"] = sum(r.get("critic_rounds", 0) for r in reports)
    return s


def main(argv=None) -> int:
    tag = (argv or sys.argv[1:] or ["dir"])[0]
    cfg = load_eval()
    out = Path(cfg["out"])
    ref = json.load(open(out / "ref_direction.json"))
    gal = {p["id"]: p for p in json.load(open(Path(cfg["gallery_v5"]) / "data.json"))["pages"]}
    gen = json.load(open(out / tag / "direction.json"))
    reps = json.load(open(out / tag / "reports.json"))
    rows = eval_pages(gen, ref, gal)
    s = summarize(rows, reps)
    (out / tag / "metrics.json").write_text(json.dumps(dict(summary=s, pages=rows), indent=1, default=str))
    print(json.dumps(s, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
