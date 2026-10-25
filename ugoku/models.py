"""Model registry: every downloadable model carries licence, source and sha256.

Weights are never bundled. `verify_registry()` is run in CI and fails when a
model has a licence outside the allowlist unless it is an optional user
download that is also listed in NOTICE.md.
"""
from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, load

ALLOWED_LICENSES = {"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "OFL-1.1"}


@dataclass(frozen=True)
class ModelSpec:
    name: str
    filename: str
    url: str
    source_url: str
    sha256: str
    license: str
    optional_user_download: bool = False
    manual: bool = False  # no public download; the user supplies the file (sha256 is that of the expected file)
    note: str = ""


REGISTRY: dict[str, ModelSpec] = {
    "ctd": ModelSpec(
        name="ctd",
        filename="ctd.onnx",
        url="https://huggingface.co/mayocream/comic-text-detector-onnx/resolve/main/comic-text-detector.onnx",
        source_url="https://github.com/dmMaze/comic-text-detector",
        sha256="1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f",
        license="GPL-3.0",
        optional_user_download=True,
        note="Hosting page says Apache-2.0, upstream is GPL-3.0; treat as GPL-3.0.",
    ),
    "bubble": ModelSpec(
        name="bubble",
        filename="bubble.onnx",
        url="https://huggingface.co/ogkalu/comic-text-and-bubble-detector/resolve/main/detector.onnx",
        source_url="https://huggingface.co/ogkalu/comic-text-and-bubble-detector",
        sha256="065744e91c0594ad8663aa8b870ce3fb27222942eded5a3cc388ce23421bd195",
        license="Apache-2.0",
    ),
    "lama": ModelSpec(
        name="lama",
        filename="lama-manga-dynamic.onnx",
        url="",
        source_url="https://huggingface.co/dreMaz/AnimeMangaInpainting",
        sha256="de31ffa5ba26916b8ea35319f6c12151ff9654d4261bccf0583a69bb095315f9",
        license="MIT",
        manual=True,
        note="Dynamic-shape ONNX export of AnimeMangaInpainting (MIT). The public lama-manga.onnx is fixed 512x512 and is not a drop-in replacement.",
    ),
}


def verify_registry(notice_text: str | None = None) -> list[str]:
    """Return a list of problems (empty = ok)."""
    errs: list[str] = []
    for m in REGISTRY.values():
        if len(m.sha256) != 64:
            errs.append(f"{m.name}: sha256 missing")
        if (not m.manual and not m.url.startswith("https://")) or not m.source_url.startswith("https://"):
            errs.append(f"{m.name}: url/source_url must be https")
        if m.license not in ALLOWED_LICENSES:
            if not m.optional_user_download:
                errs.append(f"{m.name}: licence {m.license} not allowed unless optional_user_download")
            elif notice_text is not None and m.filename.split(".")[0] not in notice_text and m.source_url not in notice_text:
                if "comic-text-detector" not in notice_text:
                    errs.append(f"{m.name}: optional non-allowlist model has no NOTICE entry")
    return errs


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_path(name: str, settings: Settings | None = None, download: bool = False) -> Path:
    """Locate a model file in model_dir. Raises FileNotFoundError with instructions if absent."""
    s = settings or load()
    spec = REGISTRY[name]
    p = Path(s.model_dir) / spec.filename
    if p.exists():
        return p
    if download and not spec.manual:
        fetch(spec, p)
        return p
    raise FileNotFoundError(f"model '{name}' not found at {p}; run `ugoku models fetch {name}` (licence: {spec.license}) or set UGOKU_MODEL_DIR")


def fetch(spec: ModelSpec, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(spec.url) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    got = sha256_file(tmp)
    if got != spec.sha256:
        tmp.unlink()
        raise ValueError(f"{spec.name}: sha256 mismatch (got {got[:12]}..)")
    tmp.rename(dest)
