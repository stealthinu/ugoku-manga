"""Rewrite samples/MANIFEST.sha256 for every media file under samples/ and docs/media/ (the repo policy check requires each one to be listed)."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"}
DIRS = ("samples", "docs/media")


def main() -> int:
    lines = []
    for p in sorted(q for d in DIRS for q in (ROOT / d).rglob("*")):
        if p.is_file() and p.suffix.lower() in MEDIA:
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT).as_posix()}")
    (ROOT / "samples" / "MANIFEST.sha256").write_text("\n".join(lines) + ("\n" if lines else ""))
    print(len(lines), "files listed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
