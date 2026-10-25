"""Pack finished galleries into release-asset zips (the sample galleries with video are too large for the git tree).

  python scripts/package_galleries.py GALLERY_DIR [...] --out dist/ [--tag v0.1.0]

Each zip holds what the player needs (index.html, page.html, data.json, pages/, layers/, media/, thumbs/, ...). Intermediate folders
(work/, stage/, h3/) are left out. A SHA256SUMS file is written next to the zips. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

SKIP = ("work/", "stage/", "h3/")
NOTE = """This gallery was made by ugoku from a CC0 sample work (see samples/LICENSE in the repository).
The panel clips were generated with MiniMax H3; its own licence terms apply to the clips. Open index.html through a local web server
(e.g. `python -m http.server`), not from the file system.
"""


def pack(gallery: Path, dst: Path) -> Path:
    if not (gallery / "data.json").exists():
        raise SystemExit(f"{gallery}: not a gallery (no data.json)")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(gallery.rglob("*")):
            rel = p.relative_to(gallery).as_posix()
            if p.is_file() and not rel.startswith(SKIP) and not rel.endswith((".log", ".pid")):
                z.write(p, f"{gallery.name}/{rel}")
        z.writestr(f"{gallery.name}/ABOUT.txt", NOTE)
    return dst


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("galleries", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("dist"))
    ap.add_argument("--tag", default="v0.1.0")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    sums = []
    for g in a.galleries:
        z = pack(g, a.out / f"ugoku-{a.tag}-gallery-{g.name}.zip")
        sums.append(f"{hashlib.sha256(z.read_bytes()).hexdigest()}  {z.name}")
        print(f"{z}  {z.stat().st_size / 1e6:.1f} MB")
    (a.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
