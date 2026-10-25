"""Composition: encode panel videos, retime, and write the gallery data file the player reads.

Origin: the prototype's build/compose step. The gallery is plain static files: data.json + pages/ layers/ media/ + player.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import numpy as np

TIME_SCALE = 0.7  # the generated clips run longer than reads well; the page timeline is compressed by this factor

FORMATS = {
    "mp4": ["-c:v", "libx264", "-crf", "15", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    "webm": ["-c:v", "libvpx-vp9", "-crf", "20", "-b:v", "0", "-pix_fmt", "yuv420p", "-row-mt", "1"],
}


def encode_frames(frames: list[np.ndarray], out_dir: Path, stem: str, fps: int = 24, ffmpeg: str = "ffmpeg", formats=("mp4", "webm")) -> list[Path]:
    """Encode BGR frames to <stem>.<fmt> for each format using the system ffmpeg."""
    h, w = frames[0].shape[:2]
    raw = np.stack(frames).tobytes()
    out_dir.mkdir(parents=True, exist_ok=True)
    outs = []
    for ext in formats:
        dst = out_dir / f"{stem}.{ext}"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", *FORMATS[ext], str(dst)],
                       input=raw, check=True)
        outs.append(dst)
    return outs


def retime(pages: list[dict], k: float = TIME_SCALE) -> None:
    """Compress the page timeline by k (order unchanged)."""
    for pg in pages:
        pg["total_s"] = round(pg["total_s"] * k, 2)
        for q in pg["panels"]:
            if "start" in q:
                q["start"] = round(q["start"] * k, 2)
        for lay in pg["layers"] + pg["overlays"]:
            lay["t_in"] = round(lay["t_in"] * k, 2)


def install_player(root: Path) -> None:
    src = resources.files("ugoku") / "web" / "player"
    for f in ("index.html", "index.js", "page.html", "page.js", "style.css"):
        shutil.copyfile(str(src / f), root / f)


def write_gallery(root: Path, works: list[dict], pages: list[dict], title: str = "ugoku") -> None:
    install_player(root)
    (root / "data.json").write_text(json.dumps(dict(title=title, works=works, pages=pages), ensure_ascii=False, indent=1), encoding="utf-8")
