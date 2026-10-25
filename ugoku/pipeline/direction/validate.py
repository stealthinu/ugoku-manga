"""Direction validator: ranges and semantics that a structured-output schema cannot express.

Origin: the prototype's direction checker (type/rect/anim/preset/banned-word/emotion/static-with-lettering rules) plus the gaps it left:
timing, total length, mode, seed, preset names, unit coverage, one-way verbs with a returning mode.
`validate_page` returns a list of `Issue`; errors must be fixed (or degraded) before a page is accepted, warnings go to the critic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .io import PRESETS

BANNED = re.compile(r"\b(glow|glowing|sparkle|sparkles|sparkling|shine|shining|light|wind|breeze|cinematic|dramatic)\b", re.I)
ONE_WAY = re.compile(
    r"\b(walks? (?:past|by|away|toward|towards)|passes?|passing|enters?|entering|kicks?|kicking|throws?|throwing|falls?|falling|leaves?|leaving"
    r"|runs? (?:past|away|toward|towards)|steps? (?:forward|back)|jumps? (?:out|away))\b",
    re.I,
)
ANIMS = ("pop", "fade", "shake", "slide")
TOL = 0.05  # rect tolerance relative to the panel (5%)


@dataclass
class Issue:
    level: str  # error | warn
    code: str
    target: str
    msg: str

    def __str__(self) -> str:
        return f"{self.level} {self.code} [{self.target}] {self.msg}"


def _grow(r, tol=TOL):
    """Limits of a panel rect grown by `tol` of its size."""
    return (r[0] - tol * r[2], r[1] - tol * r[3], r[0] + r[2] * (1 + tol), r[1] + r[3] * (1 + tol))


def _inside(r, lim=(0.0, 0.0, 1.0, 1.0), tol=0.01) -> bool:
    return len(r) == 4 and r[2] > 0 and r[3] > 0 and r[0] >= lim[0] - tol and r[1] >= lim[1] - tol and r[0] + r[2] <= lim[2] + tol and r[1] + r[3] <= lim[3] + tol


def n_sentences(s: str) -> int:
    return len([x for x in re.split(r"(?<=[.!?])\s+", s.strip()) if x])


def validate_page(pg: dict, unit_kinds: dict | None = None, sfx_detected: int = 0) -> list[Issue]:
    """pg: one page of ugoku-direction/1. unit_kinds: {unit id: kind after observation}; every unit with kind != noise must be used exactly once."""
    iss: list[Issue] = []

    def err(code, target, msg):
        iss.append(Issue("error", code, target, msg))

    def warn(code, target, msg):
        iss.append(Issue("warn", code, target, msg))

    panels = pg.get("panels", [])
    ids = [p["id"] for p in panels]
    if not panels:
        err("no_panels", pg.get("page", ""), "page has no panels")
    if len(set(ids)) != len(ids):
        err("dup_panel", pg.get("page", ""), "duplicate panel ids")
    total = pg.get("total_s", 0)
    if not (7 <= total <= 12):
        err("total_s", pg.get("page", ""), f"total_s {total} outside 7-12")
    orders = [p.get("order", 0) for p in panels]
    if sorted(orders) != list(range(1, len(panels) + 1)):
        err("panel_order", pg.get("page", ""), "panel order is not contiguous 1..n")
    pby = {p["id"]: p for p in panels}
    for p in panels:
        q = p["id"]
        t = p.get("type")
        if t not in ("h3_full", "static", "keep"):
            err("type", q, f"bad type {t}")
            continue
        if not _inside(p.get("rect", [])):
            err("rect", q, f"panel rect outside the page {p.get('rect')}")
        ts = p.get("timing_s")
        if ts is not None and not (0 <= ts[0] < ts[1] <= total + 1e-6):
            err("timing", q, f"timing_s {ts} outside [0, total_s]")
        if t == "keep":
            continue
        if t == "h3_full":
            a = p.get("action", "")
            if not a:
                err("action", q, "h3_full without action")
            if BANNED.search(a):
                err("banned", q, f"banned word {BANNED.search(a).group(0)!r} in action")
            if a and not (1 <= n_sentences(a) <= 3):
                err("action_len", q, f"action has {n_sentences(a)} sentences (1-3)")
            if p.get("magnitude") not in ("medium", "large"):
                err("magnitude", q, f"magnitude {p.get('magnitude')} must be medium or large")
            if p.get("mode") not in ("f", "fl"):
                err("mode", q, "h3_full needs mode f or fl")
            elif p.get("mode") == "fl" and ONE_WAY.search(a):
                warn("one_way_fl", q, f"one-way verb {ONE_WAY.search(a).group(0)!r} with mode fl (the clip returns to the start pose)")
            if not p.get("emotion_source") and not p.get("no_character"):
                err("emotion_source", q, "emotion_source empty")
            if "seed" in p and not isinstance(p["seed"], int):
                err("seed", q, "seed must be an integer")
        else:
            if not p.get("reason"):
                err("reason", q, "static without reason")
    used: dict[str, int] = {}
    prev = None
    for b in sorted(pg.get("bubbles", []), key=lambda b: b.get("order", 0)):
        q = b["id"]
        pan = pby.get(b.get("panel"))
        if pan is None:
            err("bubble_panel", q, f"unknown panel {b.get('panel')}")
        elif not _inside(b["rect"], _grow(pan["rect"])):
            warn("rect_in_panel", q, "bubble rect not inside its panel (5% tolerance)")
        if not _inside(b["rect"]):
            err("rect", q, "bubble rect outside the page")
        if b.get("anim") not in ANIMS:
            err("anim", q, f"bad anim {b.get('anim')}")
        if prev is not None and b["t_in"] < prev - 1e-6:
            err("t_in_order", q, "t_in decreases with reading order")
        prev = b["t_in"]
        if b.get("unit"):
            used[b["unit"]] = used.get(b["unit"], 0) + 1
    orders = sorted(b.get("order", 0) for b in pg.get("bubbles", []))
    if orders != list(range(1, len(orders) + 1)):
        err("bubble_order", pg.get("page", ""), "bubble order is not contiguous 1..n")
    for f in pg.get("fx", []):
        q = f["id"]
        pan = pby.get(f.get("panel"))
        if pan is None:
            err("fx_panel", q, f"unknown panel {f.get('panel')}")
        if f.get("kind") not in ("sfx", "manpu", "screen"):
            err("fx_kind", q, f"bad kind {f.get('kind')}")
        if f.get("preset") not in PRESETS:
            err("preset", q, f"preset {f.get('preset')!r} is not one of the player presets")
        if not _inside(f["rect"]):
            err("rect", q, "fx rect outside the page")
        elif pan is not None and not _inside(f["rect"], _grow(pan["rect"])):
            warn("rect_in_panel", q, "fx rect not inside its panel (5% tolerance)")
        if f.get("unit"):
            used[f["unit"]] = used.get(f["unit"], 0) + 1
        if pan is not None and pan.get("type") == "static" and f.get("kind") == "sfx" and not pan.get("no_character"):
            err("text_moves_char_frozen", q, "an SFX moves in a static panel with a character (make the panel h3_full or mark no_character)")
    if unit_kinds:
        for u, k in unit_kinds.items():
            if k != "noise" and used.get(u, 0) != 1:
                err("unit_use", u, f"unit used {used.get(u, 0)} times (must be exactly once)")
    if sfx_detected and not pg.get("fx"):
        warn("no_fx", pg.get("page", ""), "SFX candidates were detected but fx is empty")
    for m in pg.get("must", []):
        if not m.get("item") or not m.get("how"):
            err("must", pg.get("page", ""), "must entry without item or how")
    return iss


def errors(iss: list[Issue]) -> list[Issue]:
    return [i for i in iss if i.level == "error"]
