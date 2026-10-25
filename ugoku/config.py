"""Settings. Precedence: environment (UGOKU_*) > ~/.config/ugoku/config.toml > defaults.

No absolute paths live in code; everything machine-specific comes from here.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


def config_path() -> Path:
    return Path(os.environ.get("UGOKU_CONFIG", Path.home() / ".config" / "ugoku" / "config.toml"))


def cache_dir() -> Path:
    return Path(os.environ.get("UGOKU_CACHE", Path.home() / ".cache" / "ugoku"))


@dataclass
class Settings:
    model_dir: Path = field(default_factory=lambda: cache_dir() / "models")
    work_dir: Path = field(default_factory=lambda: Path("ugoku-work"))
    threads: int = 2
    ffmpeg: str = "ffmpeg"
    runner: dict = field(default_factory=dict)  # [runner] table: kind = local | external_command, plus its options
    # private evaluation data (never committed); see eval/README.md
    eval_dir: Path | None = None
    eval_ref: Path | None = None
    eval_out: Path | None = None
    eval_models: Path | None = None


_PATHS = {"model_dir", "work_dir", "eval_dir", "eval_ref", "eval_out", "eval_models"}


def _coerce(name: str, value):
    if name in _PATHS:
        return Path(value).expanduser()
    if name == "threads":
        return int(value)
    return value


def load(path: Path | None = None) -> Settings:
    s = Settings()
    p = path or config_path()
    data: dict = {}
    if p.exists():
        with open(p, "rb") as f:
            data = tomllib.load(f)
        # eval keys may live in an [eval] table
        for k, v in data.pop("eval", {}).items():
            data.setdefault(f"eval_{k}", v)
    for f in fields(s):
        if f.name in data:
            setattr(s, f.name, _coerce(f.name, data[f.name]))
        env = os.environ.get("UGOKU_" + f.name.upper())
        if env and f.name != "runner":
            setattr(s, f.name, _coerce(f.name, env))
    return s
