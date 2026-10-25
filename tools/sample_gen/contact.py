"""Contact sheet of a work's pages (for the manual look the acceptance asks for): python -m tools.sample_gen.contact samples/<work> out.png"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main() -> int:
    pages = sorted((Path(sys.argv[1]) / "pages").glob("*.png"))
    h = 700
    ims = [Image.open(p).convert("RGB") for p in pages]
    ims = [i.resize((round(i.width * h / i.height), h)) for i in ims]
    sheet = Image.new("RGB", (sum(i.width for i in ims) + 10 * len(ims), h + 10), "#888")
    x = 5
    for i in ims:
        sheet.paste(i, (x, 5))
        x += i.width + 10
    sheet.save(sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
