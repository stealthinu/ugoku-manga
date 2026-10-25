"""Convert the reference (earlier prototype) direction files into ugoku-direction/1. Output stays private (eval out dir).

Mapping notes:
- panel type v3_keep -> keep; h3_full / static unchanged
- h3_full panel rect: the reference pixel rect from the stage spec when present (so the stage rect is reproduced exactly)
- bubbles / fx move from inside panels to page level with a `panel` reference
- fx marked as video-baked (overlay=false or a note saying so) -> baked=true
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

from .common import load_eval

BAKED_NOTES = ("H3 動画内", "H3 内", "H3 生成内", "H3内")


def convert(cfg) -> dict:
    spec = {}
    if cfg.get("spec_v4") and Path(cfg["spec_v4"]).exists():
        spec = {p["id"]: p for p in json.load(open(cfg["spec_v4"]))["panels"]}
    pages_out = []
    for wf in sorted(Path(cfg["direction_v5"]).glob("*.json")):
        d = json.load(open(wf, encoding="utf-8"))
        for pg in d["pages"]:
            pid = pg["page"]
            img = cv2.imread(str(cfg["pages"] / f"{pid}.png"))
            H, W = img.shape[:2]
            panels, bubbles, fx = [], [], []
            for p in pg["panels"]:
                typ = {"v3_keep": "keep"}.get(p["type"], p["type"])
                rect = p["rect"]
                if p["id"] in spec and typ == "h3_full":
                    x0, y0, x1, y1 = spec[p["id"]]["src_rect"]
                    rect = [x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H]
                q = dict(id=p["id"], order=p.get("order", 0), rect=rect, type=typ)
                for k in ("role", "content", "reason", "action", "magnitude", "mode", "timing_s", "emotion_source", "seed"):
                    if k in p:
                        q[k] = p[k]
                panels.append(q)
                for i, b in enumerate(p.get("bubbles", [])):
                    bubbles.append(dict(id=f"{p['id']}-b{i}", panel=p["id"], rect=b["rect"], text=b.get("text", ""), order=b["order"], t_in=b["t_in"], anim=b["anim"]))
                for i, f in enumerate(p.get("fx", [])):
                    o = dict(id=f"{p['id']}-f{i}", panel=p["id"], rect=f["rect"], text=f.get("text", ""), kind=f["kind"], preset=f["preset"], t_in=f["t_in"])
                    if f.get("overlay") is False or any(k in f.get("note", "") for k in BAKED_NOTES):
                        o["baked"] = True
                    fx.append(o)
            pages_out.append(dict(page=pid, image=f"{pid}.png", w=W, h=H, total_s=pg.get("total_s", 10), panels=panels, bubbles=bubbles, fx=fx))
    return dict(format="ugoku-direction/1", work="eval", reading="rtl", pages=pages_out)


def main() -> int:
    cfg = load_eval()
    d = convert(cfg)
    out = Path(cfg["out"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "ref_direction.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print("pages", len(d["pages"]), "panels", sum(len(p["panels"]) for p in d["pages"]), "->", out / "ref_direction.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
