"""README demo media from finished galleries: an animated GIF and a still per page, and optionally a screenshot of a running web UI.

  python scripts/build_demo_media.py --page GALLERY_DIR:p01 [--page ...] --out docs/media [--width 360] [--fps 10] [--webui http://localhost:8771]

The page is composited with ugoku.pipeline.export.render_page_mp4 (no browser), then turned into a palette GIF with ffmpeg.
Output names: <work>-<page>.gif and <work>-<page>.png, where <work> is the gallery directory name. The web UI screenshot needs Playwright.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ugoku.pipeline.export import render_page_mp4  # noqa: E402


def page_media(gallery: Path, page: str, out: Path, width: int, fps: int, ffmpeg: str = "ffmpeg") -> list[Path]:
    name = f"{gallery.name}-{page}"
    gif, png = out / f"{name}.gif", out / f"{name}.png"
    with tempfile.TemporaryDirectory() as t:
        mp4 = render_page_mp4(gallery, page, Path(t) / "page.mp4", ffmpeg=ffmpeg, tail_s=1.5)
        vf = f"fps={fps},scale={width}:-2:flags=lanczos"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(mp4), "-vf", f"{vf},split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                        "-loop", "0", str(gif)], check=True)
        subprocess.run([ffmpeg, "-v", "error", "-y", "-sseof", "-0.2", "-i", str(mp4), "-frames:v", "1", "-vf", f"scale={width * 2}:-2:flags=lanczos", str(png)], check=True)
    return [gif, png]


def webui_shot(url: str, dst: Path) -> Path:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 800})
        pg.goto(url, wait_until="networkidle")
        pg.screenshot(path=str(dst))
        b.close()
    return dst


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--page", action="append", default=[], help="GALLERY_DIR:PAGE_ID, repeatable")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "media")
    ap.add_argument("--width", type=int, default=360)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--webui", help="URL of a running `ugoku serve` to screenshot (saved as webui.png)")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    made = []
    for spec in a.page:
        g, _, page = spec.rpartition(":")
        made += page_media(Path(g), page, a.out, a.width, a.fps)
    if a.webui:
        made.append(webui_shot(a.webui, a.out / "webui.png"))
    for m in made:
        print(f"{m.relative_to(ROOT) if m.is_relative_to(ROOT) else m}  {m.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
