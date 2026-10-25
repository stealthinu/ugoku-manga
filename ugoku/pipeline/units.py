"""Text-unit candidates of one page (balloons, free text, SFX groups) as numbered, serialisable items.

The units come from `segment.Page` (balloon/free text) plus the SFX word groups left over after balloons are removed.
Masks are kept at 1/DS scale so panel assignment can be recomputed after panel corrections without re-running the detector.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

DS = 4  # mask downscale factor


@dataclass
class Unit:
    id: str
    kind: str  # balloon | free | sfx   (a detector-level guess; the LLM decides the semantic kind)
    box: list  # normalized [x0, y0, x1, y1]
    mask: np.ndarray  # bool, 1/DS scale, covers the whole page
    txt: np.ndarray  # bool, 1/DS scale, text pixels of the unit

    def bbox(self) -> list:
        return [self.box[0], self.box[1], self.box[2] - self.box[0], self.box[3] - self.box[1]]


class UnitSet:
    def __init__(self, units: list[Unit], W: int, H: int):
        self.units, self.W, self.H = units, W, H

    def by_id(self, uid: str) -> Unit:
        return next(u for u in self.units if u.id == uid)

    def px_rect(self, u: Unit) -> list:
        return [round(u.box[0] * self.W), round(u.box[1] * self.H), round(u.box[2] * self.W), round(u.box[3] * self.H)]

    def save(self, path: Path) -> None:
        path = Path(path)
        meta = dict(W=self.W, H=self.H, units=[dict(id=u.id, kind=u.kind, box=u.box) for u in self.units])
        path.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
        np.savez_compressed(path.with_suffix(".npz"), **{f"m_{u.id}": u.mask for u in self.units}, **{f"t_{u.id}": u.txt for u in self.units})

    @classmethod
    def load(cls, path: Path) -> UnitSet:
        path = Path(path)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        z = np.load(path.with_suffix(".npz"))
        return cls([Unit(u["id"], u["kind"], u["box"], z[f"m_{u['id']}"], z[f"t_{u['id']}"]) for u in meta["units"]], meta["W"], meta["H"])


def _ds(m: np.ndarray) -> np.ndarray:
    h, w = m.shape
    return cv2.resize(m.astype(np.uint8), (w // DS, h // DS), interpolation=cv2.INTER_AREA) > 0


def analyze_units(img: np.ndarray) -> UnitSet:
    from .segment import Page

    P = Page(img)
    H, W = P.H, P.W
    units: list[Unit] = []
    union = np.zeros((H, W), np.uint8)
    for u in P.units:
        union |= u["mask"]
    for i, u in enumerate(P.units):
        x0, y0, x1, y1 = u["box"]
        t = np.zeros((H, W), np.uint8)
        t[y0:y1, x0:x1] = P.txt[y0:y1, x0:x1]
        units.append(Unit(f"U{i + 1}", u["kind"], [x0 / W, y0 / H, x1 / W, y1 / H], _ds(u["mask"]), _ds(t)))
    k = len(units)
    for j, g in enumerate(P.sfx_groups(union)):
        ys, xs = np.where(g)
        x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
        if (x1 - x0) * (y1 - y0) < 0.0004 * W * H:  # specks of screentone or line art
            continue
        units.append(Unit(f"U{k + j + 1}", "sfx", [x0 / W, y0 / H, x1 / W, y1 / H], _ds(g), _ds(g)))
    return UnitSet(units, W, H)
