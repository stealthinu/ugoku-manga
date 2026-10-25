"""FastAPI app: upload a page image or a zip, run the pipeline through the SQLite job queue, follow progress over SSE, edit directions, export."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from ..config import load
from ..pipeline.export import page_html, render_page_mp4
from .stages import Store, edit_direction, project_state, regenerate, remove_project_files, zip_dir
from .workers import Pool

MAX_UPLOAD = int(os.environ.get("UGOKU_MAX_UPLOAD_MB", "500")) << 20
BACKENDS = ("dummy", "comfy_h3", "minimax_api")
DIRECTIONS = ("heuristic", "llm", "upload")
PROVIDERS = ("claude_cli", "anthropic", "openai_compat", "gemini")
SAFE = re.compile(r"^[A-Za-z0-9_.\-]+$")
STAGES = ("ingest", "direct", "prep", "video", "compose")


def _ui_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "web" / "ui"


def create_app(data_dir: Path | str, cpu_workers: int = 2, gpu_workers: int = 1, start_workers: bool = True) -> FastAPI:
    store = Store(data_dir)
    pool = Pool(store, cpu=cpu_workers, gpu=gpu_workers)

    @asynccontextmanager
    async def lifespan(_app):
        if start_workers:
            pool.start()
        yield
        pool.stop()

    app = FastAPI(title="ugoku", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.store, app.state.pool = store, pool

    def proj_or_404(pid: str) -> dict:
        p = store.db.project(pid) if SAFE.match(pid) else None
        if not p:
            raise HTTPException(404, "no such project")
        return p

    # ---------------------------------------------------------------- UI
    @app.get("/", response_class=HTMLResponse)
    def index():
        return (_ui_dir() / "index.html").read_text(encoding="utf-8")

    @app.get("/ui/{name}")
    def ui_file(name: str):
        if not SAFE.match(name) or not (_ui_dir() / name).is_file():
            raise HTTPException(404)
        return FileResponse(_ui_dir() / name)

    # ---------------------------------------------------------------- projects
    @app.post("/api/projects")
    async def create_project(file: UploadFile = File(...), name: str = Form(""), reading: str = Form("rtl"), rights: str = Form(""), backend: str = Form("dummy"),
                             direction: str = Form("heuristic"), provider: str = Form("claude_cli"), model: str = Form(""), direction_file: UploadFile | None = File(None)):
        if rights.lower() not in ("1", "true", "on", "yes"):
            raise HTTPException(400, "confirm that you have the right to process these pages")
        if reading not in ("rtl", "ltr") or backend not in BACKENDS or direction not in DIRECTIONS or (direction == "llm" and provider not in PROVIDERS):
            raise HTTPException(400, "bad option")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in (".zip", ".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            raise HTTPException(400, "upload a png/jpg/webp image or a zip of images")
        pid = uuid.uuid4().hex[:12]
        d = store.sub(pid, "upload")
        dst = d / f"upload{suffix}"
        size = 0
        with dst.open("wb") as f:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    f.close()
                    remove_project_files(store, pid)
                    raise HTTPException(413, "file too large")
                f.write(chunk)
        if direction == "upload":
            if direction_file is None:
                remove_project_files(store, pid)
                raise HTTPException(400, "direction=upload needs a direction file")
            try:
                up = json.loads((await direction_file.read()).decode("utf-8"))
                assert up.get("format") == "ugoku-direction/1" and isinstance(up.get("pages"), list)
            except Exception:  # noqa: BLE001
                remove_project_files(store, pid)
                raise HTTPException(400, "the direction file must be ugoku-direction/1 JSON") from None
            (store.pdir(pid) / "direction_upload.json").write_text(json.dumps(up, ensure_ascii=False), encoding="utf-8")
        nm = (name or Path(file.filename or "project").stem)[:80]
        store.db.add_project(pid, nm, reading, backend, direction, provider, model)
        store.db.enqueue(pid, "", "ingest", {"input": str(dst)})
        return {"id": pid}

    @app.get("/api/projects")
    def list_projects():
        return [dict(id=p["id"], name=p["name"], state=p["state"], created=p["created"], backend=p["backend"], direction=p["direction"]) for p in store.db.projects()]

    def summary(pid: str) -> dict:
        p = proj_or_404(pid)
        jobs = store.db.jobs(pid)
        if p["state"] not in ("done", "failed"):
            p["state"] = project_state(store, pid)
        per = {}
        for st in STAGES:
            js = [j for j in jobs if j["stage"] == st]
            per[st] = dict(total=len(js), done=sum(j["status"] == "done" for j in js), running=sum(j["status"] == "running" for j in js), failed=sum(j["status"] == "failed" for j in js))
        run = [j for j in jobs if j["status"] == "running"]
        cur = run[0] if run else None
        n = len(store.db.pages(pid))
        weights = dict(ingest=5, direct=30, prep=30, video=30, compose=5)
        frac = {}
        for st in STAGES:
            js = [j for j in jobs if j["stage"] == st]
            total = n if st in ("direct", "prep") and n else len(js)
            part = sum(1.0 if j["status"] == "done" else (j["pct"] / 100 if j["status"] == "running" else 0.0) for j in js)
            frac[st] = min(1.0, part / total) if total else 0.0
        pct = 100.0 if p["state"] == "done" else min(99.0, sum(weights[st] * frac[st] for st in STAGES))
        start = min([j["created"] for j in jobs], default=time.time())
        el = time.time() - start
        eta = (el * (100 - pct) / pct) if 3 < pct < 100 else None
        tail = [f"{j['stage']} {j['page'] or ''} {j['status']} {j['msg'] or ''}".strip() for j in sorted(jobs, key=lambda j: -j["updated"] if j["updated"] else 0)[:6]]
        return dict(id=pid, name=p["name"], state=p["state"], error=p["error"], stage=cur["stage"] if cur else None, pct=round(pct, 1), eta_s=None if eta is None else round(eta),
                    log_tail=tail, stages=per, backend=p["backend"], direction=p["direction"])

    @app.get("/api/projects/{pid}")
    def project(pid: str):
        s = summary(pid)
        jobs = store.db.jobs(pid)
        pages = []
        for pg in store.db.pages(pid):
            chips = {st: next((j["status"] for j in jobs if j["page"] == pg["page"] and j["stage"] == st), "pending") for st in ("direct", "prep")}
            pages.append(dict(page=pg["page"], w=pg["w"], h=pg["h"], **chips))
        s["pages"] = pages
        s["video"] = next((j["status"] for j in jobs if j["stage"] == "video"), "pending")
        s["compose"] = next((j["status"] for j in jobs if j["stage"] == "compose"), "pending")
        return s

    @app.delete("/api/projects/{pid}")
    def delete_project(pid: str):
        proj_or_404(pid)
        j = [x for x in store.db.jobs(pid) if x["status"] == "running"]
        if j:
            raise HTTPException(409, "a job of this project is running")
        store.db.delete_project(pid)
        remove_project_files(store, pid)
        return {"ok": True}

    @app.get("/api/projects/{pid}/events")
    async def events(pid: str, request: Request):
        proj_or_404(pid)

        async def gen():
            last = None
            idle = 0
            while True:
                if await request.is_disconnected():
                    return
                s = summary(pid)
                key = json.dumps(s, sort_keys=True)
                if key != last:
                    last = key
                    idle = 0
                    yield f"data: {key}\n\n"
                else:
                    idle += 1
                    if idle % 20 == 0:
                        yield ": keepalive\n\n"
                if s["state"] in ("done", "failed") and idle > 2:
                    yield "event: end\ndata: {}\n\n"
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------------------------------------------------------- files (Range-capable)
    @app.get("/p/{pid}/{path:path}")
    def project_file(pid: str, path: str):
        proj_or_404(pid)
        root = (store.pdir(pid)).resolve()
        f = (root / path).resolve()
        if root not in f.parents or not f.is_file() or path.split("/")[0] not in ("out", "input", "dir", "exports"):
            raise HTTPException(404)
        return FileResponse(f)  # Starlette's FileResponse answers Range requests, which video seeking needs

    # ---------------------------------------------------------------- stage editing
    def page_or_404(pid: str, page: str) -> Path:
        proj_or_404(pid)
        f = store.pdir(pid) / "dir" / f"{page}.json"
        if not SAFE.match(page) or not f.exists():
            raise HTTPException(404, "direction not ready")
        return f

    @app.get("/api/projects/{pid}/pages/{page}/direction")
    def get_direction(pid: str, page: str):
        return json.loads(page_or_404(pid, page).read_text(encoding="utf-8"))

    @app.put("/api/projects/{pid}/pages/{page}/direction")
    async def put_direction(pid: str, page: str, request: Request):
        page_or_404(pid, page)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "body must be JSON") from None
        errs = edit_direction(store, pid, page, body)
        if errs:
            return JSONResponse({"errors": errs}, status_code=422)
        return {"ok": True}

    @app.post("/api/projects/{pid}/pages/{page}/regenerate")
    async def post_regenerate(pid: str, page: str, request: Request):
        page_or_404(pid, page)
        b = await request.json()
        errs = regenerate(store, pid, page, b.get("panel", ""), b.get("seed"), b.get("action"))
        if errs:
            return JSONResponse({"errors": errs}, status_code=422)
        return {"ok": True}

    # ---------------------------------------------------------------- exports
    def finished(pid: str) -> Path:
        p = proj_or_404(pid)
        out = store.pdir(pid) / "out"
        if p["state"] != "done" or not (out / "data.json").exists():
            raise HTTPException(409, "the project is not finished")
        return out

    @app.get("/api/projects/{pid}/export/gallery.zip")
    def export_gallery(pid: str):
        out = finished(pid)
        dst = store.sub(pid, "exports") / "gallery.zip"
        zip_dir(out, dst, skip=("work/", "stage/"))
        return FileResponse(dst, filename="gallery.zip", media_type="application/zip")

    @app.get("/api/projects/{pid}/export/clips.zip")
    def export_clips(pid: str):
        out = finished(pid)
        dst = store.sub(pid, "exports") / "clips.zip"
        zip_dir(out / "media", dst)
        return FileResponse(dst, filename="clips.zip", media_type="application/zip")

    @app.get("/api/projects/{pid}/export/page/{page}.html")
    def export_html(pid: str, page: str):
        out = finished(pid)
        if not SAFE.match(page):
            raise HTTPException(404)
        try:
            html = page_html(out, page)
        except StopIteration:
            raise HTTPException(404, "no such page") from None
        return HTMLResponse(html, headers={"Content-Disposition": f'attachment; filename="{page}.html"'})

    @app.get("/api/projects/{pid}/export/page/{page}.mp4")
    def export_mp4(pid: str, page: str):
        out = finished(pid)
        if not SAFE.match(page):
            raise HTTPException(404)
        dst = store.sub(pid, "exports") / f"{page}.mp4"
        try:
            render_page_mp4(out, page, dst, ffmpeg=load().ffmpeg)
        except StopIteration:
            raise HTTPException(404, "no such page") from None
        return FileResponse(dst, filename=f"{page}.mp4", media_type="video/mp4")

    return app
