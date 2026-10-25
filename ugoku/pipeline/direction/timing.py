"""Timing computed by code (the LLM does not set seconds): panel windows, unit entrances, page length, default seeds.

Model (fitted to the earlier hand-written directions): a panel starts 0.6 s before the previous one ends; its first line enters 0.6 s after the
start; lines follow every 0.4-0.8 s depending on the previous line's length; SFX and manpu enter at start + 0.3 s, staggered by 0.4 s;
a panel lasts until its last entrance + 0.8 s (at least 2.4 s). The page length is the end of the last panel + 0.4 s, clamped to 7-12 s
by compressing the timeline when it is too long.
"""
from __future__ import annotations

import hashlib

OVERLAP, FIRST, MIN_PANEL = 0.6, 0.6, 2.4
TOTAL_MIN, TOTAL_MAX = 7.0, 12.0


def gap_after(text: str) -> float:
    return min(0.8, 0.4 + 0.03 * len(text or ""))


def default_seed(panel_id: str) -> int:
    return int(hashlib.sha1(panel_id.encode()).hexdigest()[:6], 16) % 100000


def compute_timing(panels: list[dict]) -> tuple[dict, float]:
    """panels: in reading order, each {id, lines: [{id, text}], fx: [{id}]}. Returns ({id: (a, b), unit id: t_in...}, total_s)."""
    out: dict = {}
    start = 0.0
    last_end = 0.0
    for p in panels:
        t = start + FIRST
        hi = start
        for ln in p["lines"]:
            out[ln["id"]] = t
            hi = max(hi, t)
            t += gap_after(ln.get("text", ""))
        for j, fx in enumerate(p["fx"]):
            out[fx["id"]] = start + 0.3 + 0.4 * j
            hi = max(hi, out[fx["id"]])
        end = max(hi + 0.8, start + MIN_PANEL)
        out[p["id"]] = (start, end)
        last_end = end
        start = end - OVERLAP
    total = last_end + 0.4
    k = TOTAL_MAX / total if total > TOTAL_MAX else 1.0
    total = min(max(total * k, TOTAL_MIN), TOTAL_MAX)
    res = {}
    for key, v in out.items():
        res[key] = (round(v[0] * k, 1), round(v[1] * k, 1)) if isinstance(v, tuple) else round(v * k, 2)
    return res, round(total, 1)
