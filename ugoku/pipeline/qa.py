"""Text-leak QA for generated clips: did the video model draw letters or sound-effect characters that the source panel did not have?

Origin: the prototype's QA step. Every 12th frame is segmented with the text detector (probability > 0.4); text that is not in the first frame
(dilated by 9 px) and not under the dilated (17 px) mask of the removed lettering counts as new. The clip is flagged when the worst frame has
more than 0.4% of the panel covered by new text.
"""
from __future__ import annotations

import cv2
import numpy as np

from .detect.text import text_probability

THRESH = 0.4
STEP = 12
FLAG_AT = 0.004


def read_frames(path: str) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    out = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(f)
    cap.release()
    return out


def qa_text(frames: list[np.ndarray], exclude: np.ndarray | None = None) -> dict:
    """frames: BGR frames of one clip. exclude: uint8 mask (panel size) of lettering removed from the source panel."""
    h, w = frames[0].shape[:2]
    ex = np.zeros((h, w), np.uint8) if exclude is None else cv2.dilate((exclude > 0).astype(np.uint8), np.ones((17, 17), np.uint8))
    t0 = text_probability(frames[0]) > THRESH
    t0 = cv2.dilate(t0.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    worst, at = 0.0, 0
    for i in range(STEP, len(frames), STEP):
        t = (text_probability(frames[i]) > THRESH) & ~t0 & (ex == 0)
        t = cv2.morphologyEx(t.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        r = float(t.mean())
        if r > worst:
            worst, at = r, i
    return dict(new_text=round(worst, 4), frame=at, flag=worst > FLAG_AT)
