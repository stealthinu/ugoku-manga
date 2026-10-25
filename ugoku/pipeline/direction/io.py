"""Load direction files (format ugoku-direction/1). Full validation arrives with the LLM direction phase."""
from __future__ import annotations

import json
from pathlib import Path

FORMAT = "ugoku-direction/1"

PRESETS = (
    "impact jolt tremble pulse sway creep slide drop repeat_pop rhythm tick drip pop stretch line_stretch sparkle_blink flicker mail_slide"
).split()


def load_direction(path: Path | str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("format") != FORMAT:
        raise ValueError(f"unsupported direction format: {d.get('format')!r}")
    return d


def page_by_id(direction: dict, page_id: str) -> dict:
    for pg in direction["pages"]:
        if pg["page"] == page_id:
            return pg
    raise KeyError(page_id)
