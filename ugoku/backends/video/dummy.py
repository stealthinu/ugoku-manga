"""Dummy video backend: a slow push-in on the panel image. For CI, UI work and layout checks; no model needed."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .base import PanelJob


class DummyBackend:
    name = "dummy"

    def __init__(self, ffmpeg: str = "ffmpeg", zoom: float = 0.03):
        self.ffmpeg = ffmpeg
        self.zoom = zoom

    def frames(self, job: PanelJob) -> list[np.ndarray]:
        img = cv2.imread(str(job.image))
        h, w = img.shape[:2]
        out = []
        for i in range(job.frames):
            s = 1 + self.zoom * np.sin(np.pi * i / (job.frames - 1)) if job.mode == "fl" else 1 + self.zoom * i / (job.frames - 1)
            M = cv2.getRotationMatrix2D((w / 2, h / 2), 0, s)
            out.append(cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE))
        return out

    def generate(self, job: PanelJob, out: Path) -> Path:
        from ...pipeline.compose import encode_frames

        out.parent.mkdir(parents=True, exist_ok=True)
        encode_frames(self.frames(job), out.parent, out.stem, fps=job.fps, ffmpeg=self.ffmpeg)  # mp4 and webm side by side
        return out
