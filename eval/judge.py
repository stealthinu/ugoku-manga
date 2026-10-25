"""LLM visual judge for generated clips: a frame sheet plus the source panel, scored 1-5 on a fixed rubric (advisory, calibrated on the reference clips)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ugoku.pipeline.qa import read_frames

RUBRIC = ["matches_action", "physically_plausible", "consistent_drawing", "no_invented_text", "stable_background", "overall"]
SCHEMA = {
    "type": "object",
    "properties": {**{k: {"type": "integer"} for k in RUBRIC}, "notes": {"type": "string"}},
    "required": RUBRIC + ["notes"],
    "additionalProperties": False,
}
PROMPT = """You are judging a short generated video clip made from one manga panel (black and white). Two images are attached: the source panel (first) and a sheet of 8 frames
from the clip, in time order from left to right and top to bottom. The intended action was:

"{action}"

Score each item from 1 (very bad) to 5 (very good):
- matches_action: the clip shows the intended action clearly (a still or barely moving clip scores 1-2).
- physically_plausible: motion has weight and cause and effect; nobody walks backwards or moves in reverse; nothing teleports.
- consistent_drawing: faces, line art and proportions stay the same drawing, with no melting or morphing.
- no_invented_text: no letters, numbers or sound-effect characters appear that the source panel did not have (5 = none).
- stable_background: panel borders, screentone and background stay put unless the action moves them.
- overall: your overall impression of whether this clip would look good in a moving manga.
Give integers only and one short sentence of notes."""


def sheet(video: str, src: np.ndarray, out: Path, n: int = 8, cols: int = 4, width: int = 1500) -> tuple[Path, Path]:
    fr = read_frames(video)
    idx = np.linspace(0, len(fr) - 1, n).round().astype(int)
    h, w = fr[0].shape[:2]
    cw = width // cols
    ch = round(cw * h / w)
    tiles = [cv2.resize(fr[i], (cw, ch), interpolation=cv2.INTER_AREA) for i in idx]
    rows = [np.hstack(tiles[r * cols:(r + 1) * cols]) for r in range(n // cols)]
    out.parent.mkdir(parents=True, exist_ok=True)
    sp, tp = out.with_suffix(".src.png"), out.with_suffix(".sheet.png")
    s = cv2.resize(src, (cw * 2, round(cw * 2 * h / w)), interpolation=cv2.INTER_AREA) if src.shape[1] != cw * 2 else src
    cv2.imwrite(str(sp), s)
    cv2.imwrite(str(tp), np.vstack(rows))
    return sp, tp


def judge(provider, video: str, src_bgr: np.ndarray, action: str, work: Path, key: str) -> dict:
    sp, tp = sheet(video, src_bgr, work / key)
    r = provider.complete(PROMPT.format(action=action), images=[sp, tp], schema=SCHEMA, tag=f"judge:{key}")
    return {k: int(r[k]) for k in RUBRIC} | {"notes": str(r.get("notes", ""))[:200]}


SEM_SCHEMA = {
    "type": "object",
    "properties": {
        "direction_ok": {"type": "boolean"},
        "reverse_motion": {"type": "boolean"},
        "added_text_or_sfx": {"type": "boolean"},
        "motion_visible": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": ["direction_ok", "reverse_motion", "added_text_or_sfx", "motion_visible", "notes"],
    "additionalProperties": False,
}
SEM_PROMPT = """Two images are attached: a black and white manga panel (first) and a sheet of 8 frames from a generated clip of it, in time order from left to right and top to bottom.
The direction given for the clip was:

"{action}"

Answer from the frames only. Left and right are as seen on screen.
- direction_ok: every left/right/up/down movement and every gaze or gesture direction in the frames matches the direction text.
- reverse_motion: a character walks, runs or moves backwards, or the motion plays in reverse (feet or body move against the facing direction).
- added_text_or_sfx: letters, numbers or sound-effect characters appear in the frames that are not in the source panel.
- motion_visible: the frames show clear movement of the described subject (not a near-still clip).
One short sentence of notes."""


def semantics(provider, video: str, src_bgr: np.ndarray, action: str, work: Path, key: str) -> dict:
    sp, tp = sheet(video, src_bgr, work / key)
    r = provider.complete(SEM_PROMPT.format(action=action), images=[sp, tp], schema=SEM_SCHEMA, tag=f"sem:{key}")
    return {k: bool(r[k]) for k in SEM_SCHEMA["required"][:-1]} | {"notes": str(r.get("notes", ""))[:200]}
