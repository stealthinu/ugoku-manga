"""Command line entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def cmd_models(a) -> int:
    from .config import load
    from .models import REGISTRY, fetch, model_path

    s = load()
    if a.action == "list":
        for m in REGISTRY.values():
            try:
                where = str(model_path(m.name, s))
            except FileNotFoundError:
                where = "(missing)"
            print(f"{m.name:8s} {m.license:10s} {where}")
        return 0
    for n in a.names or REGISTRY:
        fetch(REGISTRY[n], Path(s.model_dir) / REGISTRY[n].filename)
        print("fetched", n)
    return 0


def cmd_run(a) -> int:
    from .pipeline.run import run_pages

    return run_pages(a.images, Path(a.direction), Path(a.out), backend=a.backend, stop_after=a.stop_after, procs=a.procs)


def cmd_direct(a) -> int:
    """Generate a direction file from page images with the vision-LLM workflow."""
    import json

    import cv2

    from .backends.llm import CachedProvider, LoginError, make_provider
    from .config import cache_dir
    from .pipeline.direction.workflow import direct_page, wrap_direction

    kw = {"model": a.model} if a.model else {}
    if a.provider == "replay":
        kw["recording"] = a.replay
    inner = make_provider(a.provider, **kw)
    prov = inner if a.provider == "replay" else CachedProvider(inner, Path(a.cache or cache_dir() / "llm-cache"))
    work = Path(a.work)
    pages, reports = [], []
    try:
        for f in a.images:
            img = cv2.imread(str(f))
            pid = Path(f).stem
            pg, rep = direct_page(img, pid, prov, work / pid, a.reading)
            pages.append(pg)
            reports.append(rep)
            print(pid, "valid" if rep["valid"] else "INVALID", "degraded:" + str(len(rep["degraded"])))
    except LoginError as e:
        print("provider login failed:", e, file=sys.stderr)
        return 3
    out = Path(a.out)
    out.write_text(json.dumps(wrap_direction(pages, a.name, a.reading, prov), ensure_ascii=False, indent=1), encoding="utf-8")
    out.with_name(out.stem + "_report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def cmd_serve(a) -> int:
    import ipaddress

    try:
        import uvicorn

        from .server.app import create_app
    except ImportError:
        print("the web UI needs the server extra: pip install 'ugoku[server]'", file=sys.stderr)
        return 2
    try:
        local = ipaddress.ip_address(a.host).is_loopback
    except ValueError:
        local = a.host == "localhost"
    if not local and not a.public:
        print(f"refusing to bind {a.host}: the UI has no login; pass --public to expose it on the network", file=sys.stderr)
        return 2
    app = create_app(a.data, cpu_workers=a.cpu_workers, gpu_workers=a.gpu_workers)
    uvicorn.run(app, host=a.host, port=a.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ugoku", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("models", help="list or fetch model weights")
    m.add_argument("action", choices=["list", "fetch"])
    m.add_argument("names", nargs="*")
    m.set_defaults(fn=cmd_models)
    r = sub.add_parser("run", help="build a moving-manga gallery from pages and a direction file")
    r.add_argument("images", nargs="+")
    r.add_argument("--direction", required=True, help="direction JSON (ugoku-direction/1)")
    r.add_argument("--out", required=True)
    r.add_argument("--backend", default="dummy", choices=["dummy", "comfy_h3", "minimax_api"])
    r.add_argument("--stop-after", choices=["prep", "video", "compose"], default="compose")
    r.add_argument("--procs", type=int, default=2)
    r.set_defaults(fn=cmd_run)
    d = sub.add_parser("direct", help="write a direction file from page images using a vision LLM (needs an API key unless --provider claude_cli)")
    d.add_argument("images", nargs="+")
    d.add_argument("--out", required=True)
    d.add_argument("--provider", default="anthropic", choices=["anthropic", "openai_compat", "gemini", "claude_cli", "replay"])
    d.add_argument("--model", default=None)
    d.add_argument("--reading", default="rtl", choices=["rtl", "ltr"])
    d.add_argument("--name", default="work")
    d.add_argument("--work", default="ugoku-work/direction", help="where the images shown to the LLM are written")
    d.add_argument("--cache", default=None, help="response cache directory")
    d.add_argument("--replay", default=None, help="recording directory for --provider replay")
    d.set_defaults(fn=cmd_direct)
    sv = sub.add_parser("serve", help="start the web UI (needs the server extra)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8771)
    sv.add_argument("--public", action="store_true", help="allow binding a non-loopback address (the UI has no login)")
    sv.add_argument("--data", default="ugoku-data", help="project and database directory")
    sv.add_argument("--cpu-workers", type=int, default=2)
    sv.add_argument("--gpu-workers", type=int, default=1)
    sv.set_defaults(fn=cmd_serve)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
