"""ComfyUI whole-panel video backend. Packs a stage directory, hands it to a runner (this machine or an external queue), unpacks the mp4s."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from ...pipeline.compose import FORMATS
from ..runner import RunnerError, make_runner
from .base import PanelJob

JOB_SCRIPT = Path(__file__).resolve().parents[2] / "gpu_scripts" / "comfy_h3_job.py"


def est_seconds(n_panels: int, per_panel_s: float = 840.0) -> float:
    return n_panels * per_panel_s


class ComfyH3Backend:
    name = "comfy_h3"

    def __init__(self, runner: dict | None = None, ffmpeg: str = "ffmpeg", per_panel_s: float = 840.0, work_dir: Path | str = "ugoku-work/h3"):
        self.runner = make_runner(runner)
        self.ffmpeg, self.per_panel_s, self.work_dir = ffmpeg, per_panel_s, Path(work_dir)

    def pack(self, jobs: list[PanelJob], stage_dir: Path) -> None:
        (stage_dir / "in").mkdir(parents=True, exist_ok=True)
        panels = []
        for j in jobs:
            shutil.copyfile(j.image, stage_dir / "in" / f"{j.id}.png")
            panels.append(dict(id=j.id, file=f"in/{j.id}.png", action=j.action, magnitude=j.magnitude, mode=j.mode, seed=j.seed))
        frames = {j.frames for j in jobs}
        if len(frames) > 1:
            raise ValueError("all panels of one batch must use the same frame count")
        (stage_dir / "spec.json").write_text(json.dumps(dict(panels=panels, frames=frames.pop()), ensure_ascii=False, indent=1), encoding="utf-8")
        shutil.copyfile(JOB_SCRIPT, stage_dir / "comfy_h3_job.py")
        sums = []
        for p in sorted(stage_dir.rglob("*")):
            rel = p.relative_to(stage_dir).as_posix()
            if p.is_file() and (rel.startswith("in/") or rel in ("spec.json", "comfy_h3_job.py")):
                sums.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {rel}")
        (stage_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n")

    def generate_batch(self, jobs: list[PanelJob], out_dir: Path, tag: str | None = None) -> dict[str, str]:
        """Returns {panel id: 'ok' or an error text}. Writes out_dir/<id>.mp4 (+ .webm)."""
        if not jobs:
            return {}
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(json.dumps([[j.id, j.action, j.magnitude, j.mode, j.seed, j.frames, hashlib.sha256(Path(j.image).read_bytes()).hexdigest()] for j in jobs]).encode()).hexdigest()[:10]
        job_id = tag or f"h3-{time.strftime('%Y%m%d-%H%M%S')}-{key}"
        stage = self.work_dir / job_id  # a re-run of the same batch finds submission.json and resumes polling instead of submitting twice
        if not (stage / "spec.json").exists():
            self.pack(jobs, stage)
        res = Path(self.runner.run(stage, job_id, len(jobs), est_seconds(len(jobs), self.per_panel_s)))
        man = json.loads((res / "manifest.json").read_text(encoding="utf-8"))
        status = {}
        for j in jobs:
            m = man["items"].get(j.id, {})
            src = res / "out" / f"{j.id}.mp4"
            if m.get("status") == "ok" and src.exists():
                shutil.copyfile(src, out_dir / f"{j.id}.mp4")
                self._webm(out_dir / f"{j.id}.mp4")
                status[j.id] = "ok"
            else:
                status[j.id] = m.get("error") or "missing from the result"
        return status

    def generate(self, job: PanelJob, out: Path) -> Path:
        st = self.generate_batch([job], out.parent)[job.id]
        if st != "ok":
            raise RunnerError(f"{job.id}: {st}")
        if out.name != f"{job.id}.mp4":
            shutil.move(out.parent / f"{job.id}.mp4", out)
        return out

    def _webm(self, mp4: Path) -> None:
        webm = mp4.with_suffix(".webm")
        subprocess.run([self.ffmpeg, "-y", "-loglevel", "error", "-i", str(mp4), *FORMATS["webm"], str(webm)], check=True)
