"""Stage executors for the server queue and the project directory layout.

project/<id>/  input/<page>.png  dir/<page>.json (direction of one page)  out/ (gallery: pages, layers, stage, media, data.json)  meta/<page>.json  exports/
Stages: ingest -> direct (per page) -> prep (per page) -> video (project, GPU pool) -> compose (project). `advance()` enqueues the next stage once its inputs are done.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import cv2
import numpy as np

from ..backends.video.base import PanelJob
from ..config import cache_dir, load
from ..pipeline.compose import TIME_SCALE, retime, write_gallery
from ..pipeline.run import generate_videos
from ..pipeline.stage import prepare_page, write_files
from .db import DB

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_PAGES = 300
MAX_UNZIPPED = 1 << 30
MAX_SIDE = 6000


class StageError(RuntimeError):
    def __init__(self, msg: str, retry: bool = False):
        super().__init__(msg)
        self.retry = retry


class Store:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = DB(self.root / "ugoku.sqlite")

    def pdir(self, pid: str) -> Path:
        return self.root / "projects" / pid

    def sub(self, pid: str, name: str) -> Path:
        d = self.pdir(pid) / name
        d.mkdir(parents=True, exist_ok=True)
        return d


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _decode(data: bytes) -> np.ndarray | None:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    return img


def read_pages(path: Path) -> list[tuple[str, np.ndarray]]:
    """An image file or a zip of images -> [(name, BGR image)] in natural order. Zip entries with unsafe names are skipped."""
    if path.suffix.lower() == ".zip":
        out = []
        with zipfile.ZipFile(path) as z:
            infos = [i for i in z.infolist() if not i.is_dir() and Path(i.filename).suffix.lower() in IMG_EXT and "__MACOSX" not in i.filename
                     and ".." not in Path(i.filename).parts and not i.filename.startswith("/")]
            if sum(i.file_size for i in infos) > MAX_UNZIPPED:
                raise StageError("zip is too large when unpacked")
            for i in sorted(infos, key=lambda i: natural_key(i.filename)):
                img = _decode(z.read(i))
                if img is not None:
                    out.append((Path(i.filename).stem, img))
        if not out:
            raise StageError("no readable images in the zip")
        if len(out) > MAX_PAGES:
            raise StageError(f"too many pages ({len(out)} > {MAX_PAGES})")
        return out
    img = _decode(path.read_bytes())
    if img is None:
        raise StageError("not a readable image")
    return [(path.stem, img)]


# ------------------------------------------------------------------ executors
def do_ingest(store: Store, job: dict, progress) -> dict:
    pid = job["project"]
    src = Path(job["payload"]["input"])
    pages = read_pages(src)
    inp = store.sub(pid, "input")
    rows = []
    for i, (name, img) in enumerate(pages):
        page = f"p{i + 1:03d}"
        cv2.imwrite(str(inp / f"{page}.png"), img)
        rows.append((page, img.shape[1], img.shape[0]))
        progress(100 * (i + 1) / len(pages), f"{i + 1}/{len(pages)} pages")
    store.db.add_pages(pid, rows)
    (store.pdir(pid) / "names.json").write_text(json.dumps({r[0]: n for r, (n, _) in zip(rows, pages)}, ensure_ascii=False), encoding="utf-8")
    for page, _, _ in rows:
        store.db.enqueue(pid, page, "direct")
    return dict(pages=len(rows))


def _provider(store: Store, proj: dict):
    from ..backends.llm import CachedProvider, make_provider

    kw = {"model": proj["model"]} if proj.get("model") else {}
    return CachedProvider(make_provider(proj["provider"], **kw), cache_dir() / "llm-cache")


def do_direct(store: Store, job: dict, progress) -> dict:
    pid, page = job["project"], job["page"]
    proj = store.db.project(pid)
    img = cv2.imread(str(store.pdir(pid) / "input" / f"{page}.png"))
    dd = store.sub(pid, "dir")
    mode = proj["direction"]
    if mode == "upload":
        up = json.loads((store.pdir(pid) / "direction_upload.json").read_text(encoding="utf-8"))
        pages = up["pages"]
        idx = int(page[1:]) - 1
        pg = next((p for p in pages if p.get("page") == page), pages[idx] if idx < len(pages) else None)
        if pg is None:
            raise StageError(f"the uploaded direction has no entry for {page}")
        pg = dict(pg, page=page, image=f"{page}.png", w=img.shape[1], h=img.shape[0])
    elif mode == "llm":
        from ..backends.llm import LoginError
        from ..pipeline.direction.workflow import direct_page

        try:
            pg, rep = direct_page(img, page, _provider(store, proj), store.sub(pid, "work") / page, proj["reading"])
        except LoginError as e:  # no fallback to another provider
            raise StageError(f"provider login failed: {e}") from e
        (dd / f"{page}_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        from ..pipeline.direction.heuristic import heuristic_page

        pg, _ = heuristic_page(img, page, proj["reading"])
    (dd / f"{page}.json").write_text(json.dumps(pg, ensure_ascii=False, indent=1), encoding="utf-8")
    return {}


def do_prep(store: Store, job: dict, progress) -> dict:
    pid, page = job["project"], job["page"]
    proj = store.db.project(pid)
    img = cv2.imread(str(store.pdir(pid) / "input" / f"{page}.png"))
    pg = json.loads((store.pdir(pid) / "dir" / f"{page}.json").read_text(encoding="utf-8"))
    entry, rep, stage, files = prepare_page(img, pg, proj["name"])
    out = store.sub(pid, "out")
    write_files(out, files)
    mp = store.sub(pid, "meta") / f"{page}.json"
    old = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    mp.write_text(json.dumps(dict(entry=entry, report=rep, stage=stage), ensure_ascii=False), encoding="utf-8")
    drop_stale_media(out / "media", old.get("stage", []), stage)
    return dict(layers=len(entry["layers"]), video_inputs=len(stage))


def spec_of(s: dict) -> tuple:
    return (s["action"], s["magnitude"], s["mode"], s["seed"], s["file"])


def drop_stale_media(media: Path, old: list[dict], new: list[dict]) -> None:
    """Remove the clips of panels whose spec changed (or that no longer exist), so the video stage regenerates only those."""
    keep = {s["id"]: spec_of(s) for s in new}
    for s in old:
        if keep.get(s["id"]) != spec_of(s):
            for ext in ("mp4", "webm"):
                (media / f"{s['id']}.{ext}").unlink(missing_ok=True)


def do_video(store: Store, job: dict, progress) -> dict:
    pid = job["project"]
    proj = store.db.project(pid)
    out = store.sub(pid, "out")
    jobs = []
    for page in store.db.pages(pid):
        meta = json.loads((store.pdir(pid) / "meta" / f"{page['page']}.json").read_text(encoding="utf-8"))
        for s in meta["stage"]:
            jobs.append(PanelJob(id=s["id"], image=out / "stage" / s["file"], action=s["action"], magnitude=s["magnitude"], mode=s["mode"], seed=s["seed"]))
    settings = load()
    media = out / "media"
    todo = [j for j in jobs if not (media / f"{j.id}.mp4").exists()]
    if proj["backend"] == "dummy":
        from ..backends.video.dummy import DummyBackend

        be = DummyBackend(ffmpeg=settings.ffmpeg)
        for i, j in enumerate(todo):
            be.generate(j, media / f"{j.id}.mp4")
            progress(100 * (i + 1) / max(1, len(todo)), f"{i + 1}/{len(todo)} clips")
    else:
        progress(1, f"{len(todo)} clips submitted to the video backend")
        generate_videos(settings, proj["backend"], jobs, media, store.sub(pid, "work"))
    return dict(clips=len(jobs), generated=len(todo))


def do_compose(store: Store, job: dict, progress) -> dict:
    pid = job["project"]
    proj = store.db.project(pid)
    out = store.sub(pid, "out")
    pages = []
    for page in store.db.pages(pid):
        meta = json.loads((store.pdir(pid) / "meta" / f"{page['page']}.json").read_text(encoding="utf-8"))
        pages.append(meta["entry"])
    stage = [s for page in store.db.pages(pid) for s in json.loads((store.pdir(pid) / "meta" / f"{page['page']}.json").read_text(encoding="utf-8"))["stage"]]
    from ..pipeline.stage import write_spec

    write_spec(out, stage)
    retime(pages, TIME_SCALE)
    write_gallery(out, [dict(id=proj["name"], title=proj["name"])], pages, title=proj["name"])
    return dict(pages=len(pages))


EXEC = {"ingest": do_ingest, "direct": do_direct, "prep": do_prep, "video": do_video, "compose": do_compose}


def advance(store: Store, pid: str) -> None:
    """Enqueue what became ready after a job finished. Idempotent."""
    db = store.db
    proj = db.project(pid)
    if proj is None or proj["state"] in ("failed",):
        return
    pages = db.pages(pid)
    if not pages:
        return
    for p in pages:
        d, pr = db.job(pid, p["page"], "direct"), db.job(pid, p["page"], "prep")
        if d and d["status"] == "done" and pr is None:
            db.enqueue(pid, p["page"], "prep")
    preps = [db.job(pid, p["page"], "prep") for p in pages]
    if all(j and j["status"] == "done" for j in preps):
        v = db.job(pid, "", "video")
        if v is None:
            db.enqueue(pid, "", "video")
        elif v["status"] == "done":
            c = db.job(pid, "", "compose")
            if c is None:
                db.enqueue(pid, "", "compose")
            elif c["status"] == "done":
                db.set_project(pid, state="done")


def project_state(store: Store, pid: str) -> str:
    jobs = store.db.jobs(pid)
    if any(j["status"] == "failed" for j in jobs):
        return "failed"
    if jobs and all(j["status"] == "done" for j in jobs) and any(j["stage"] == "compose" for j in jobs):
        return "done"
    return "running" if jobs else "queued"


def edit_direction(store: Store, pid: str, page: str, new_pg: dict) -> list[str]:
    """Replace the direction of one page (checked first) and rerun prep for it, then video (changed clips only) and compose."""

    pg = dict(new_pg, page=page)
    img = cv2.imread(str(store.pdir(pid) / "input" / f"{page}.png"))
    pg["w"], pg["h"] = img.shape[1], img.shape[0]
    pg["image"] = f"{page}.png"
    errs = check_page(pg)
    if errs:
        return errs
    (store.sub(pid, "dir") / f"{page}.json").write_text(json.dumps(pg, ensure_ascii=False, indent=1), encoding="utf-8")
    # only prep is rerun now; video and compose are dropped and re-created by advance() once every prep is done again (no stale compose)
    store.db.enqueue(pid, page, "prep", force=True)
    store.db.drop(pid, "", "video")
    store.db.drop(pid, "", "compose")
    store.db.set_project(pid, state="queued")
    return []


def check_page(pg: dict) -> list[str]:
    errs = []
    if not isinstance(pg.get("panels"), list) or not pg["panels"]:
        return ["panels must be a non-empty list"]
    ids = set()
    for p in pg["panels"]:
        r = p.get("rect")
        ok = isinstance(r, list) and len(r) == 4 and all(isinstance(v, (int, float)) for v in r)
        if not (ok and 0 <= r[0] <= 1 and 0 <= r[1] <= 1 and r[2] > 0 and r[3] > 0 and r[0] + r[2] <= 1.001 and r[1] + r[3] <= 1.001):
            errs.append(f"{p.get('id')}: rect must be [x, y, w, h] as page fractions inside the page")
        if p.get("type") not in ("h3_full", "static", "keep"):
            errs.append(f"{p.get('id')}: bad type")
        if p.get("type") == "h3_full":
            if not str(p.get("action", "")).strip():
                errs.append(f"{p.get('id')}: h3_full needs an action")
            if p.get("mode") not in ("f", "fl"):
                errs.append(f"{p.get('id')}: mode must be f or fl")
            if p.get("magnitude") not in ("medium", "large"):
                errs.append(f"{p.get('id')}: magnitude must be medium or large")
        ids.add(p.get("id"))
    for u in pg.get("bubbles", []) + pg.get("fx", []):
        if u.get("panel") not in ids:
            errs.append(f"{u.get('id')}: unknown panel {u.get('panel')}")
    return errs


def regenerate(store: Store, pid: str, page: str, panel_id: str, seed: int | None = None, action: str | None = None) -> list[str]:
    path = store.pdir(pid) / "dir" / f"{page}.json"
    pg = json.loads(path.read_text(encoding="utf-8"))
    for p in pg["panels"]:
        if p["id"] == panel_id and p["type"] == "h3_full":
            p["seed"] = seed if seed is not None else (int(p.get("seed", 0)) * 1103515245 + 12345) % 2147483647
            if action:
                p["action"] = action
            break
    else:
        return [f"no animated panel {panel_id}"]
    return edit_direction(store, pid, page, pg)


def zip_dir(src: Path, dst: Path, skip: tuple[str, ...] = ()) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file() and not any(f.relative_to(src).as_posix().startswith(s) for s in skip):
                z.write(f, f.relative_to(src).as_posix())
    dst.write_bytes(buf.getvalue())
    return dst


def remove_project_files(store: Store, pid: str) -> None:
    shutil.rmtree(store.pdir(pid), ignore_errors=True)
