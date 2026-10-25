"""Open-licence (OFL-1.1) fonts for the lettering, fetched at build time into the cache and checked against pinned sha256 values."""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

RAW = "https://github.com/google/fonts/raw/main/ofl/"
# role -> (path in the google/fonts repo, file name, variable-font weight or None)
FONTS = {
    "sans": ("notosansjp/NotoSansJP%5Bwght%5D.ttf", "NotoSansJP[wght].ttf", 600),
    "serif": ("notoserifjp/NotoSerifJP%5Bwght%5D.ttf", "NotoSerifJP[wght].ttf", 500),
    "maru": ("zenmarugothic/ZenMaruGothic-Bold.ttf", "ZenMaruGothic-Bold.ttf", None),
    "dela": ("delagothicone/DelaGothicOne-Regular.ttf", "DelaGothicOne-Regular.ttf", None),
    "rampart": ("rampartone/RampartOne-Regular.ttf", "RampartOne-Regular.ttf", None),
    "reggae": ("reggaeone/ReggaeOne-Regular.ttf", "ReggaeOne-Regular.ttf", None),
    "mochiy": ("mochiypopone/MochiyPopOne-Regular.ttf", "MochiyPopOne-Regular.ttf", None),
    "yusei": ("yuseimagic/YuseiMagic-Regular.ttf", "YuseiMagic-Regular.ttf", None),
}
FAMILY = {"sans": "Noto Sans JP", "serif": "Noto Serif JP", "maru": "Zen Maru Gothic", "dela": "Dela Gothic One", "rampart": "Rampart One",
          "reggae": "Reggae One", "mochiy": "Mochiy Pop One", "yusei": "Yusei Magic"}


def font_dir() -> Path:
    from ugoku.config import cache_dir

    d = cache_dir() / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def font_path(role: str) -> Path:
    url, name, _ = FONTS[role]
    p = font_dir() / name
    if not p.exists():
        tmp = p.with_suffix(".part")
        urllib.request.urlretrieve(RAW + url, tmp)
        tmp.replace(p)
    return p


def sha256(role: str) -> str:
    return hashlib.sha256(font_path(role).read_bytes()).hexdigest()


_cache: dict = {}


def load(role: str, size: int):
    from PIL import ImageFont

    key = (role, size)
    if key not in _cache:
        f = ImageFont.truetype(str(font_path(role)), size)
        w = FONTS[role][2]
        if w:
            try:
                f.set_variation_by_axes([w])
            except Exception:  # noqa: BLE001 - FreeType without variation support: keep the default instance
                pass
        _cache[key] = f
    return _cache[key]
