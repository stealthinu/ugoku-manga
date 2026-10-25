"""MiniMax hosted video API backend (bring your own key). Code only in this repository's development: it has never been called here.

Results differ from the local ComfyUI backend because the service pre-processes the prompt and picks its own resolution.
Field names follow the public API description (`first_frame_image`, `last_frame_image`, task polling); check them against the current docs before use.
Key: env MINIMAX_API_KEY. The panel image is sent as a data URL, so it leaves this machine: only use pages you have the right to send.
"""
from __future__ import annotations

import base64
import os
import subprocess
import time
from pathlib import Path

import requests

from .base import PanelJob


class MiniMaxError(RuntimeError):
    pass


class MiniMaxBackend:
    name = "minimax_api"

    def __init__(self, base_url: str = "https://api.minimax.io", model: str = "MiniMax-H3", poll_s: float = 10, timeout_s: float = 1800,
                 api_key_env: str = "MINIMAX_API_KEY", ffmpeg: str = "ffmpeg", session=None, sleep=time.sleep):
        self.base, self.model, self.poll_s, self.timeout_s = base_url.rstrip("/"), model, poll_s, timeout_s
        self.key_env, self.ffmpeg, self.http, self.sleep = api_key_env, ffmpeg, session or requests, sleep

    def _headers(self) -> dict:
        key = os.environ.get(self.key_env)
        if not key:
            raise MiniMaxError(f"{self.key_env} is not set")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    @staticmethod
    def _data_url(p: Path) -> str:
        return "data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode()

    def _prompt(self, job: PanelJob) -> str:
        from ...gpu_scripts.comfy_h3_job import make_prompt  # same wording as the local backend, minus the reference-picture preamble

        full = make_prompt(job.action, job.magnitude, job.frames, job.mode)
        return full.split("[Shot 1] ", 1)[1].split("\n\noverall_soundscape", 1)[0]

    def submit(self, job: PanelJob) -> str:
        img = self._data_url(job.image)
        body = dict(model=self.model, prompt=self._prompt(job), first_frame_image=img, duration=round(job.frames / job.fps))
        if job.mode == "fl":
            body["last_frame_image"] = img
        r = self.http.post(f"{self.base}/v1/video_generation", json=body, headers=self._headers(), timeout=120)
        r.raise_for_status()
        d = r.json()
        code = d.get("base_resp", {}).get("status_code", 0)
        if code != 0 or "task_id" not in d:
            raise MiniMaxError(f"submit rejected: {d.get('base_resp')}")
        return d["task_id"]

    def poll(self, task_id: str) -> tuple[str, str | None]:
        r = self.http.get(f"{self.base}/v1/query/video_generation", params={"task_id": task_id}, headers=self._headers(), timeout=60)
        r.raise_for_status()
        d = r.json()
        return str(d.get("status", "")), d.get("file_id")

    def fetch(self, file_id: str) -> bytes:
        r = self.http.get(f"{self.base}/v1/files/retrieve", params={"file_id": file_id}, headers=self._headers(), timeout=60)
        r.raise_for_status()
        url = r.json()["file"]["download_url"]
        v = self.http.get(url, timeout=300)
        v.raise_for_status()
        return v.content

    def generate(self, job: PanelJob, out: Path) -> Path:
        tid = self.submit(job)
        t0 = time.time()
        while True:
            st, fid = self.poll(tid)
            if st.lower() == "success" and fid:
                break
            if st.lower() in ("fail", "failed"):
                raise MiniMaxError(f"task {tid} failed")
            if time.time() - t0 > self.timeout_s:
                raise MiniMaxError(f"task {tid} timed out")
            self.sleep(self.poll_s)
        out.parent.mkdir(parents=True, exist_ok=True)
        raw = out.with_suffix(".raw.mp4")
        raw.write_bytes(self.fetch(fid))
        # match the source panel size and make it grayscale like the local backend
        from PIL import Image

        w, h = Image.open(job.image).size
        subprocess.run([self.ffmpeg, "-y", "-loglevel", "error", "-i", str(raw), "-vf", f"scale={w // 2 * 2}:{h // 2 * 2}:flags=lanczos,format=gray,format=yuv420p",
                        "-c:v", "libx264", "-crf", "15", "-movflags", "+faststart", str(out)], check=True)
        raw.unlink()
        return out
