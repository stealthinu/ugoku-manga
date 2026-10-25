"""Sample-work builder.

  python -m tools.sample_gen.build art  <work>... --out DIR    write the art-generation stage dir (spec.json + job scripts) for the GPU runner
  python -m tools.sample_gen.build render <work>... --art DIR   assemble pages, truth.json and masks into samples/<work>/

The art stage is run by `ugoku.backends.runner` (any runner); results come back as DIR/result/out/<page>_<panel>.png.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import yaml

from . import render as R

ROOT = Path(__file__).resolve().parents[2]
CANVASES = [(1024, 1024), (1152, 896), (896, 1152), (1216, 832), (832, 1216), (1344, 768), (768, 1344), (1536, 640)]
DENY_IN_PROMPTS = ("in the style of", "style of", "by artist", "artstation", "pixiv", "trending", "studio ghibli", "disney", "pokemon", "naruto", "one piece", "dragon ball")


def load_script(work: str) -> dict:
    return yaml.safe_load((ROOT / "samples" / work / "script.yaml").read_text(encoding="utf-8"))


def panel_rects(script: dict, page: dict):
    st = script["style"]
    rects = R.koma_rects(page) if page.get("layout") == "koma" else R.layout_rects(page, st.get("margin", 40), st.get("gutter", 14))
    return rects


def canvas_for(rect) -> tuple[int, int]:
    ar = (rect[2] - rect[0]) / (rect[3] - rect[1])
    return min(CANVASES, key=lambda c: abs(c[0] / c[1] - ar))


def prompt_for(script: dict, page: dict, pn: dict) -> str:
    art = script["art"]
    p = pn["prompt"]
    for k, v in script.get("characters", {}).items():
        p = p.replace(f"<{k}>", v)
    space = pn.get("space", "none")
    sp = "" if space == "none" or not art.get("use_space", True) else f", with a large empty plain area in the {space} of the frame"
    prefix = art["prefix_color"] if pn.get("color") and "prefix_color" in art else art["prefix"]
    return prefix + p + sp + art["suffix"]


def art_spec(works: list[str]) -> dict:
    imgs = []
    for w in works:
        s = load_script(w)
        for page in s["pages"]:
            rects = panel_rects(s, page)
            for pn, r in zip(page["panels"], rects):
                if pn.get("fill") == "black":
                    continue
                cw, ch = canvas_for(r)
                prompt = prompt_for(s, page, pn)
                low = prompt.lower()
                assert not any(d in low for d in DENY_IN_PROMPTS), f"denied phrase in prompt of {w} {page['id']} {pn['id']}"
                imgs.append(dict(id=f"{w}__{page['id']}_{pn['id']}", prompt=prompt, negative=s["art"]["negative"], w=cw, h=ch, seed=pn["seed"]))
    return dict(steps=20, cfg=2.5, images=imgs)


def cmd_art(a) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    spec = art_spec(a.works)
    (out / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    here = Path(__file__).resolve().parent
    shutil.copyfile(here / "art_job.py", out / "art_job.py")
    shutil.copyfile(ROOT / "ugoku" / "gpu_scripts" / "comfy_h3_job.py", out / "comfy_h3_job.py")
    print(len(spec["images"]), "images ->", out)
    return 0


def cmd_render(a) -> int:
    for w in a.works:
        s = load_script(w)
        art_dir = Path(a.art) / w
        art_dir.mkdir(parents=True, exist_ok=True)
        # art files are stored as <work>__<page>_<panel>.png in --art; link them under the work name
        for f in Path(a.art).glob(f"{w}__*.png"):
            shutil.copyfile(f, art_dir / f.name.split("__", 1)[1])
        t = R.render_work(s, art_dir, ROOT / "samples" / w)
        print(w, len(t["pages"]), "pages", sum(len(p["units"]) for p in t["pages"]), "units")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("art")
    p.add_argument("works", nargs="+")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_art)
    p = sub.add_parser("render")
    p.add_argument("works", nargs="+")
    p.add_argument("--art", required=True)
    p.set_defaults(fn=cmd_render)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
