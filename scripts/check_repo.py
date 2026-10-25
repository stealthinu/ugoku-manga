"""Repo policy checks: media files only under samples/, tests/fixtures/ and docs/media/ (listed in samples/MANIFEST.sha256), size cap, model licence allowlist."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".onnx", ".safetensors", ".ckpt"}
ALLOWED_DIRS = ("samples/", "tests/fixtures/", "docs/media/")
MAX_BYTES = 5 * 1024 * 1024


def tracked() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True)
    return [x for x in out.splitlines() if (ROOT / x).is_file()]


def main() -> int:
    errs: list[str] = []
    man = ROOT / "samples" / "MANIFEST.sha256"
    listed = {}
    if man.exists():
        for line in man.read_text().splitlines():
            if line.strip():
                h, _, name = line.partition("  ")
                listed[name.strip()] = h
    for f in tracked():
        p = ROOT / f
        if p.stat().st_size > MAX_BYTES:
            errs.append(f"{f}: larger than 5 MB")
        if p.suffix.lower() in MEDIA:
            if not f.startswith(ALLOWED_DIRS):
                errs.append(f"{f}: media file outside samples/, tests/fixtures/ or docs/media/")
            elif f not in listed:
                errs.append(f"{f}: not listed in samples/MANIFEST.sha256")
            elif hashlib.sha256(p.read_bytes()).hexdigest() != listed[f]:
                errs.append(f"{f}: sha256 differs from MANIFEST")
    sys.path.insert(0, str(ROOT))
    from ugoku.models import verify_registry

    errs += verify_registry((ROOT / "NOTICE.md").read_text())
    for e in errs:
        print("POLICY", e)
    if not errs:
        print("repo policy: ok")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
