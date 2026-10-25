"""Video backend interface: one panel image + action -> an mp4 of the same size."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class PanelJob:
    id: str
    image: Path
    action: str
    magnitude: str = "medium"
    mode: str = "fl"
    seed: int = 0
    frames: int = 124
    fps: int = 24


class VideoBackend(Protocol):
    name: str

    def generate(self, job: PanelJob, out: Path) -> Path: ...
