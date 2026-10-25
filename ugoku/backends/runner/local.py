"""Run the job script on this machine (the GPU is local)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .base import RunnerError


class LocalRunner:
    name = "local"

    def __init__(self, python: str | None = None, env: dict | None = None, timeout_factor: float = 1.5):
        self.python = python or sys.executable
        self.env = {str(k): str(v) for k, v in (env or {}).items()}
        self.timeout_factor = timeout_factor

    def run(self, stage_dir: Path, job_id: str, n_panels: int, expect_s: float) -> Path:
        stage_dir = Path(stage_dir)
        cmd = [self.python, str(stage_dir / "comfy_h3_job.py"), "--root", str(stage_dir)]
        log = (stage_dir / "job.log").open("ab")
        try:
            r = subprocess.run(cmd, cwd=stage_dir, env={**os.environ, **self.env}, stdout=log, stderr=subprocess.STDOUT, timeout=expect_s * self.timeout_factor)
        except subprocess.TimeoutExpired as e:
            raise RunnerError(f"job {job_id} timed out after {e.timeout:.0f}s") from e
        if r.returncode not in (0, 1):  # 1 = some panels failed; the manifest says which
            raise RunnerError(f"job {job_id} exited with {r.returncode} (see job.log)")
        return stage_dir
