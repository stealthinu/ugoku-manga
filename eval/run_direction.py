"""Generate a direction for the private eval pages through the LLM workflow (eval only).

The provider is `claude_cli` (the local `claude` CLI with the subscription login; API keys are stripped from the child env).
Responses are cached under `<out>/llm-cache`, so a rerun with unchanged inputs makes no LLM call.
Outputs (under `<out>/<tag>/`): direction.json, reports.json (numbers and ids only, no page text), per-page work images.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2

from ugoku.backends.llm import CachedProvider, LoginError, make_provider
from ugoku.pipeline.direction.workflow import direct_page, wrap_direction

from .common import load_eval
from .layout_eval import units_for


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="*", help="page ids (default: all eval pages)")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tag", default="dir")
    ap.add_argument("--max-calls", type=int, default=400)
    a = ap.parse_args(argv)
    cfg = load_eval()
    os.environ["UGOKU_MODEL_DIR"] = str(cfg["models"])
    ref = json.load(open(Path(cfg["out"]) / "ref_direction.json"))
    pids = a.pages or [p["page"] for p in ref["pages"]]
    out = Path(cfg["out"]) / a.tag
    out.mkdir(parents=True, exist_ok=True)
    inner = make_provider("claude_cli", model=a.model, max_calls=a.max_calls)
    prov = CachedProvider(inner, Path(cfg["out"]) / "llm-cache")
    t0 = time.time()

    def one(pid):
        img = cv2.imread(str(cfg["pages"] / f"{pid}.png"))
        us = units_for(cfg, pid)
        try:
            pg, rep = direct_page(img, pid, prov, out / "work" / pid, "rtl", us)
        except LoginError:
            raise
        except Exception as e:  # keep going; the page is reported as failed
            return pid, None, dict(page=pid, valid=False, valid_without_degrade=False, error=f"{type(e).__name__}: {str(e)[:200]}")
        return pid, pg, rep

    try:
        with ThreadPoolExecutor(a.workers) as ex:
            res = list(ex.map(one, pids))
    except LoginError as e:
        print("LOGIN FAILURE, stopping (no fallback):", e, file=sys.stderr)
        return 3
    pages = [pg for _, pg, _ in res if pg]
    d = wrap_direction(pages, "eval", "rtl", prov)
    (out / "direction.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    reps = [r for _, _, r in res]
    (out / "reports.json").write_text(json.dumps(reps, indent=1), encoding="utf-8")
    u = inner.usage
    print(f"pages {len(pages)}/{len(pids)} valid {sum(r.get('valid', False) for r in reps)} no-degrade {sum(r.get('valid_without_degrade', False) for r in reps)}; "
          f"llm calls {u.calls} (cache hits {prov.usage.cache_hits}, failures {u.failures}); {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
