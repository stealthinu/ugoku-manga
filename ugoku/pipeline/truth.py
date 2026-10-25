"""Ground-truth files of the sample works (`samples/<work>/truth.json`): loading and structural validation."""
from __future__ import annotations

import json
from pathlib import Path

KINDS = {"bubble", "sfx", "manpu"}


def load_truth(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_truth(t: dict, root: Path | None = None) -> list[str]:
    """Return a list of problems (empty = valid). With `root`, also checks that referenced files exist."""
    errs: list[str] = []
    if t.get("format") != "ugoku-truth/1":
        errs.append("format must be ugoku-truth/1")
    if t.get("reading") not in ("rtl", "ltr"):
        errs.append("reading must be rtl or ltr")
    for pg in t.get("pages", []):
        pid = pg.get("page", "?")
        for k in ("page", "image", "w", "h", "panels", "units", "unit_order", "mask"):
            if k not in pg:
                errs.append(f"{pid}: missing {k}")
        if errs:
            continue
        pids = {p["id"] for p in pg["panels"]}
        if [p["order"] for p in pg["panels"]] != list(range(1, len(pg["panels"]) + 1)):
            errs.append(f"{pid}: panel order is not 1..n in list order")
        for p in pg["panels"]:
            if len(p["poly"]) < 3 or any(not (0 <= x <= pg["w"] and 0 <= y <= pg["h"]) for x, y in p["poly"]):
                errs.append(f"{p['id']}: bad polygon")
        uids = set()
        for u in pg["units"]:
            if u["kind"] not in KINDS:
                errs.append(f"{u['id']}: bad kind {u['kind']}")
            if u["panel"] not in pids:
                errs.append(f"{u['id']}: unknown panel {u['panel']}")
            x0, y0, x1, y1 = u["bbox"]
            if not (0 <= x0 < x1 <= pg["w"] and 0 <= y0 < y1 <= pg["h"]):
                errs.append(f"{u['id']}: bbox outside the page")
            uids.add(u["id"])
        if len(uids) != len(pg["units"]):
            errs.append(f"{pid}: duplicate unit ids")
        bubbles = {u["id"] for u in pg["units"] if u["kind"] == "bubble"}
        if set(pg["unit_order"]) != bubbles or len(pg["unit_order"]) != len(bubbles):
            errs.append(f"{pid}: unit_order must list every bubble once")
        if root is not None:
            for f in (pg["image"], pg["mask"]):
                if not (Path(root) / f).exists():
                    errs.append(f"{pid}: missing file {f}")
    return errs
