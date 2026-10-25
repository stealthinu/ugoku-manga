"""Eval configuration: private data locations, read from a config file outside the repo."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path


def load_eval() -> dict[str, Path]:
    p = Path(os.environ.get("UGOKU_EVAL_CONFIG", Path.home() / ".config" / "ugoku" / "eval.toml"))
    if not p.exists():
        raise SystemExit(f"eval config not found: {p} (see eval/README.md)")
    with open(p, "rb") as f:
        raw = tomllib.load(f)
    cfg = {k: Path(v).expanduser() for k, v in raw.items()}
    for k in ("pages", "direction_v5", "gallery_v5"):
        if k not in cfg:
            raise SystemExit(f"eval config missing key: {k}")
    cfg.setdefault("out", Path("eval-out"))
    return cfg
