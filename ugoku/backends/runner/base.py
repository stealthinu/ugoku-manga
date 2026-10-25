"""Runner interface: execute a prepared stage directory and return the directory holding `manifest.json` and `out/`."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class RunnerError(RuntimeError):
    pass


class Runner(Protocol):
    name: str

    def run(self, stage_dir: Path, job_id: str, n_panels: int, expect_s: float) -> Path: ...


def make_runner(cfg: dict | None):
    """Build a runner from the `[runner]` settings table. Default: run on this machine."""
    cfg = dict(cfg or {})
    kind = cfg.pop("kind", "local")
    if kind == "local":
        from .local import LocalRunner

        return LocalRunner(**cfg)
    if kind == "external_command":
        from .external_command import ExternalCommandRunner

        return ExternalCommandRunner(**cfg)
    raise RunnerError(f"unknown runner kind: {kind}")
