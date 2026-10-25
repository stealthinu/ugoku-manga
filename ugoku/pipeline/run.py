"""End-to-end driver: pages + direction file -> static moving-manga gallery."""
from __future__ import annotations

import json
import sys
from multiprocessing import get_context
from pathlib import Path

import cv2

from ..backends.video.base import PanelJob
from ..backends.video.comfy_h3 import ComfyH3Backend
from ..backends.video.dummy import DummyBackend
from ..backends.video.minimax_api import MiniMaxBackend
from ..config import load
from .compose import TIME_SCALE, retime, write_gallery
from .direction.io import load_direction
from .stage import prepare_page, write_files, write_spec


def _prep(args):
    img_path, pg, work, out = args
    cv2.setNumThreads(1)
    img = cv2.imread(str(img_path))
    entry, rep, stage, files = prepare_page(img, pg, work)
    write_files(Path(out), files)
    return entry, rep, stage


def _find_image(images: list[Path], pg: dict) -> Path:
    names = {p.stem: p for p in images} | {p.name: p for p in images}
    for key in (pg.get("image"), pg["page"]):
        if key and (key in names or Path(key).stem in names):
            return names.get(key) or names[Path(key).stem]
    raise FileNotFoundError(f"no input image for page {pg['page']}")


def prepare(images, direction: dict, out: Path, procs: int = 2):
    out.mkdir(parents=True, exist_ok=True)
    work = direction.get("work", "")
    jobs = [(_find_image(images, pg), pg, work, str(out)) for pg in direction["pages"]]
    if procs > 1:
        with get_context("spawn").Pool(procs) as pool:
            res = pool.map(_prep, jobs, chunksize=1)
    else:
        res = [_prep(j) for j in jobs]
    pages = [r[0] for r in res]
    rep = [r[1] for r in res]
    stage = [s for r in res for s in r[2]]
    write_spec(out, stage)
    (out / "build_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return pages, rep, stage


def generate_videos(settings, backend: str, jobs: list[PanelJob], media: Path, work: Path) -> None:
    """Run the chosen video backend over all panel jobs, skipping panels whose mp4 already exists."""
    todo = [j for j in jobs if not (media / f"{j.id}.mp4").exists()]
    if backend == "comfy_h3":
        be = ComfyH3Backend(runner=settings.runner, ffmpeg=settings.ffmpeg, work_dir=work / "h3")
        bad = {k: v for k, v in be.generate_batch(todo, media).items() if v != "ok"}
        if bad:
            raise RuntimeError(f"{len(bad)} panels failed: {bad}")
        return
    be = DummyBackend(ffmpeg=settings.ffmpeg) if backend == "dummy" else MiniMaxBackend(ffmpeg=settings.ffmpeg)
    for j in todo:
        be.generate(j, media / f"{j.id}.mp4")


def run_pages(images, direction_path: Path, out: Path, backend: str = "dummy", stop_after: str = "compose", procs: int = 2) -> int:
    settings = load()
    images = [Path(p) for p in images]
    direction = load_direction(direction_path)
    pages, rep, stage = prepare(images, direction, out, procs)
    for r in rep:
        for w in r["warn"]:
            print("warn", r["page"], w, file=sys.stderr)
    print(f"prepared {len(pages)} pages, {sum(len(p['layers']) for p in pages)} layers, {len(stage)} video inputs")
    if stop_after == "prep":
        return 0
    jobs = [PanelJob(id=s["id"], image=out / "stage" / s["file"], action=s["action"], magnitude=s["magnitude"], mode=s["mode"], seed=s["seed"]) for s in stage]
    generate_videos(settings, backend, jobs, out / "media", out)
    retime(pages, TIME_SCALE)
    works = [dict(id=direction.get("work", ""), title=direction.get("work", ""))]
    write_gallery(out, works, pages)
    print("gallery written to", out)
    return 0
