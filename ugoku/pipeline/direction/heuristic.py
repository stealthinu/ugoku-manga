"""Direction without any LLM: detector output only. Used when no provider is configured (and by CI with the dummy video backend).

Panels come from the classical detector in reading order; the largest ones are animated with a generic action, the rest stay still.
Transcription is not available without a model, so bubble text is empty and every unit keeps its detector kind.
"""
from __future__ import annotations

from .workflow import assemble, init_ctx

GENERIC_ACTION = "The characters shift their weight and breathe naturally, with a small clear movement of the head and hands. Starts nearly still, moves, returns to the starting pose."


def heuristic_page(img, page_id: str, reading: str = "rtl", us=None, max_animated: int = 3, min_area: float = 0.06) -> tuple[dict, object]:
    ctx = init_ctx(img, page_id, reading, us)
    areas = {p["id"]: p["bbox"][2] * p["bbox"][3] for p in ctx.panels}
    big = [pid for pid, a in sorted(areas.items(), key=lambda kv: -kv[1]) if a >= min_area][:max_animated]
    panels = []
    for p in ctx.panels:
        if p["id"] in big:
            panels.append(dict(id=p["id"], type="h3_full", role="lead" if p["id"] == big[0] else "support", action=GENERIC_ACTION, magnitude="medium", mode="fl",
                               emotion_source="", reason="largest panels are animated"))
        else:
            panels.append(dict(id=p["id"], type="static", role="hold", action="", magnitude="none", mode="none", emotion_source="", reason="small panel"))
    return assemble(ctx, dict(panels=panels, units=[])), ctx
