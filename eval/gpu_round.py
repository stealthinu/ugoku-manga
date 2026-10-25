"""GPU rounds on the fixed subset of 12 panels (2 per work). Numbers and ids only are committed.

  python -m eval.gpu_round select                       choose the 12 reference panels (stratified by the reference score, feedback pages first)
  python -m eval.gpu_round build  --tag G1 --direction D   prepare our stage inputs for the pages of the subset and match them to the reference panels
  python -m eval.gpu_round submit --tag G1              generate the clips that changed since earlier rounds (cache on the spec hash) through the configured runner
  python -m eval.gpu_round score  --tag G1              metrics, score, text-leak QA and the LLM judge; writes eval/rounds/<tag>.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

from .common import load_eval
from .metrics import iou_rect as iou


def feedback_ids(cfg) -> list[str]:
    """Reference panels that were flagged in the reviews of the earlier prototype (private list next to the reports)."""
    p = Path(cfg["out"]) / "gpu" / "feedback_ids.json"
    return json.load(open(p)) if p.exists() else []


def gdir(cfg) -> Path:
    d = Path(cfg["out"]) / "gpu"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_select(cfg, a) -> int:
    gal = Path(cfg["gallery_v5"])
    data = json.load(open(gal / "data.json"))
    sc = json.load(open(cfg["scores_v5"]))
    by_work: dict[str, list] = {}
    for p in data["pages"]:
        for q in p["panels"]:
            if q.get("mp4") and q.get("src_rect") and q["id"] in sc:
                by_work.setdefault(p["work"], []).append(
                    dict(v5_id=q["id"], page=p["id"], work=p["work"], v5_score=sc[q["id"]], src_rect=q["src_rect"], mode=q.get("mode"), action=q.get("action", ""))
                )
    fb = feedback_ids(cfg)
    pick = []
    for w in sorted(by_work):
        rows = sorted(by_work[w], key=lambda r: (r["v5_score"], r["v5_id"]))
        low = [r for r in rows if r["v5_score"] <= 3]
        fb = [r for r in low if r["v5_id"] in fb]
        lo = (fb or low or rows)[0]
        high = [r for r in rows if r["v5_score"] >= 4 and r is not lo]
        hi = sorted(high or [r for r in rows if r is not lo], key=lambda r: (-r["v5_score"], r["v5_id"]))[0]
        pick += [lo, hi]
    (gdir(cfg) / "subset.json").write_text(json.dumps(pick, ensure_ascii=False, indent=1))
    print(len(pick), "panels; v5 mean", round(float(np.mean([r["v5_score"] for r in pick])), 3), ">=4:", sum(r["v5_score"] >= 4 for r in pick))
    return 0


def spec_hash(img_path: Path, s: dict) -> str:
    h = hashlib.sha256(img_path.read_bytes())
    h.update(json.dumps([s["action"], s["magnitude"], s["mode"], s["seed"]]).encode())
    return h.hexdigest()[:16]


def cmd_build(cfg, a) -> int:
    from ugoku.pipeline.run import prepare

    os.environ["UGOKU_MODEL_DIR"] = str(cfg["models"])
    subset = json.load(open(gdir(cfg) / "subset.json"))
    direction = json.load(open(a.direction))
    pages = sorted({r["page"] for r in subset})
    dsub = dict(direction, pages=[p for p in direction["pages"] if p["page"] in pages])
    out = gdir(cfg) / a.tag
    shutil.rmtree(out, ignore_errors=True)
    images = [Path(cfg["pages"]) / f"{p}.png" for p in pages]
    _, _, stage = prepare(images, dsub, out, procs=2)
    matches, unmatched = [], []
    for r in subset:
        cands = [(iou(s["src_rect"], r["src_rect"]), s) for s in stage if s["page"] == r["page"]]
        best = max(cands, key=lambda c: c[0], default=(0, None))
        if best[1] is not None and best[0] >= 0.5:
            s = best[1]
            spec = {k: s[k] for k in ("action", "magnitude", "mode", "seed", "file")}
            matches.append(dict(v5_id=r["v5_id"], v5_score=r["v5_score"], ours=s["id"], iou=round(best[0], 3), hash=spec_hash(out / "stage" / s["file"], s), spec=spec))
        else:
            unmatched.append(dict(v5_id=r["v5_id"], v5_score=r["v5_score"], best_iou=round(best[0], 3)))
    (out / "match.json").write_text(json.dumps(dict(matches=matches, unmatched=unmatched), indent=1))
    print(len(matches), "matched,", len(unmatched), "unmatched (our direction animates no such panel)")
    return 0


def cmd_submit(cfg, a) -> int:
    from ugoku.backends.video.base import PanelJob
    from ugoku.backends.video.comfy_h3 import ComfyH3Backend
    from ugoku.config import load

    out = gdir(cfg) / a.tag
    cache = gdir(cfg) / "clips"
    cache.mkdir(exist_ok=True)
    m = json.load(open(out / "match.json"))["matches"]
    todo = [x for x in m if not (cache / f"{x['hash']}.mp4").exists()]
    print(len(m), "matched,", len(todo), "to generate")
    if todo:
        jobs = [PanelJob(id=x["hash"], image=out / "stage" / x["spec"]["file"], **{k: x["spec"][k] for k in ("action", "magnitude", "mode", "seed")}) for x in todo]
        be = ComfyH3Backend(runner=load().runner, ffmpeg=load().ffmpeg, work_dir=gdir(cfg) / "h3")
        res = be.generate_batch(jobs, cache, tag=f"oss-{a.tag}")
        print(res)
        return 0 if all(v == "ok" for v in res.values()) else 1
    return 0


def cmd_score(cfg, a) -> int:
    from ugoku.backends.llm import CachedProvider, make_provider
    from ugoku.pipeline.qa import qa_text, read_frames

    from .judge import RUBRIC, judge
    from .qa_text import exclusion
    from .score5 import clip_metrics, read_gray, score

    os.environ["UGOKU_MODEL_DIR"] = str(cfg["models"])
    out = gdir(cfg) / a.tag
    cache = gdir(cfg) / "clips"
    m = json.load(open(out / "match.json"))
    sub = {r["v5_id"]: r for r in json.load(open(gdir(cfg) / "subset.json"))}
    for p in json.load(open(Path(cfg["gallery_v5"]) / "data.json"))["pages"]:  # reference info for any matched panel, also if the subset file was regenerated since the build
        for q in p["panels"]:
            sub.setdefault(q["id"], dict(v5_id=q["id"], page=p["id"], src_rect=q.get("src_rect"), action=q.get("action", "")))
    prov = CachedProvider(make_provider("claude_cli", model=a.model), Path(cfg["out"]) / "llm-cache") if not a.no_judge else None
    gal = Path(cfg["gallery_v5"])
    rows = []
    for x in m["matches"]:
        clip = cache / f"{x['hash']}.mp4"
        if not clip.exists():
            continue
        src = cv2.imread(str(out / "stage" / x["spec"]["file"]))
        met = clip_metrics(read_gray(str(clip)), cv2.cvtColor(src, cv2.COLOR_BGR2GRAY).astype(np.float32))
        row = dict(v5_id=x["v5_id"], v5_score=x["v5_score"], ours=x["ours"], score=score(met), motion=met["motion"], sharp_min=met["sharp_min"], flick=met["flick"])
        row["qa"] = qa_text(read_frames(str(clip)), _our_exclusion(out, x))
        if prov:
            row["judge"] = judge(prov, str(clip), src, x["spec"]["action"], out / "judge", x["ours"])
            r = sub[x["v5_id"]]
            vid = gal / "media" / f"{x['v5_id']}.mp4"
            base = (gdir(cfg) / "judge_v5.json")
            jb = json.load(open(base)) if base.exists() else {}
            if x["v5_id"] not in jb:
                page_img = cv2.imread(str(gal / "pages" / f"{r['page']}.png"))
                x0, y0, x1, y1 = r["src_rect"]
                jb[x["v5_id"]] = judge(prov, str(vid), page_img[y0:y1, x0:x1], r["action"], gdir(cfg) / "judge_v5", x["v5_id"])
                base.write_text(json.dumps(jb, indent=1))
            row["judge_v5"] = jb[x["v5_id"]]
        rows.append(row)
    res = dict(tag=a.tag, rows=rows, unmatched=m["unmatched"])
    (out / "result.json").write_text(json.dumps(res, indent=1))
    n = len(rows)
    v5m = float(np.mean([r["v5_score"] for r in rows])) if n else 0
    om = float(np.mean([r["score"] for r in rows])) if n else 0
    summ = dict(n=n, unmatched=len(m["unmatched"]), score_ours=round(om, 3), score_v5_same=round(v5m, 3), ge4_ours=sum(r["score"] >= 4 for r in rows), ge4_v5=sum(r["v5_score"] >= 4 for r in rows),
                qa_flagged=sum(r["qa"]["flag"] for r in rows))
    if prov and n:
        summ["judge_ours"] = round(float(np.mean([r["judge"]["overall"] for r in rows])), 3)
        summ["judge_v5"] = round(float(np.mean([r["judge_v5"]["overall"] for r in rows])), 3)
        summ["judge_items_ours"] = {k: round(float(np.mean([r["judge"][k] for r in rows])), 2) for k in RUBRIC}
    qb = Path(cfg["out"]) / "qa_text_v5.json"
    q = json.load(open(qb)) if qb.exists() else {}
    for x in m["matches"]:  # reference QA on the same panels (computed once, cached next to the other reports)
        if x["v5_id"] not in q:
            r = sub[x["v5_id"]]
            q[x["v5_id"]] = qa_text(read_frames(str(gal / "media" / f"{x['v5_id']}.mp4")), exclusion(Path(cfg["work_v5"]), r["page"], r["src_rect"]))
            qb.write_text(json.dumps(q, indent=1))
    same = [q[x["v5_id"]]["flag"] for x in m["matches"] if x["v5_id"] in q]
    summ["qa_rate_v5_same"] = round(sum(same) / len(same), 4) if same else None
    summ["qa_rate_ours"] = round(summ["qa_flagged"] / n, 4) if n else None
    (out / "summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))
    return 0


def _our_exclusion(out: Path, x: dict) -> np.ndarray:
    """Mask of the lettering removed from our stage panel, cut from the page-level hide/flat masks."""
    f = out / "work"
    pid = x["ours"].rsplit("-p", 1)[0]
    meta = json.load(open(out / "stage" / "spec.json"))["panels"]
    s = next(p for p in meta if p["id"] == x["ours"])
    x0, y0, x1, y1 = s["src_rect"]
    ex = np.zeros((y1 - y0, x1 - x0), np.uint8)
    for k in ("hide", "flat"):
        p = f / f"{k}_{pid}.png"
        if p.exists():
            ex |= (cv2.imread(str(p), 0)[y0:y1, x0:x1] > 0).astype(np.uint8)
    return ex


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["select", "build", "submit", "score"])
    ap.add_argument("--tag", default="G1")
    ap.add_argument("--direction")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_eval()
    return dict(select=cmd_select, build=cmd_build, submit=cmd_submit, score=cmd_score)[a.cmd](cfg, a)


if __name__ == "__main__":
    sys.exit(main())
