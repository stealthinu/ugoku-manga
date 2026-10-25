"""Direction from a vision-LLM workflow: observe (A), direct (B), critic (C), reading-order tie-break, with validation, repair, degrade and cache.

Principle: the LLM judges, code measures. Panels and text units are numbered candidates found by code; the LLM refers to ids and never gives
final coordinates. Order, seconds, rects and seeds are computed here (see order.py and timing.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import numpy as np

from ..order import assign_units, band_order, order_panels
from ..panels import detect_panels
from ..units import UnitSet, analyze_units
from .inputs import write_inputs
from .io import FORMAT, PRESETS
from .panelfix import apply_panel_fixes
from .timing import compute_timing, default_seed
from .validate import Issue, errors, validate_page

PROMPT_VERSION = "p3"
TEXT_KINDS = ("dialogue", "narration")
FX_KINDS = ("sfx", "manpu", "screen")
DET_TO_KIND = {"balloon": "dialogue", "free": "narration", "sfx": "sfx"}


def _res(path: str) -> str:
    return (resources.files("ugoku") / path).read_text(encoding="utf-8")


def load_schema(name: str) -> dict:
    d = json.loads(_res(f"schema/{name}.json"))
    d.pop("$schema", None)
    return d


def load_prompt(name: str) -> str:
    return _res(f"pipeline/direction/prompts/{name}.md").replace("{rules}", _res("pipeline/direction/prompts/rules.md"))


def fill(tpl: str, **kw) -> str:
    for k, v in kw.items():
        tpl = tpl.replace("{" + k + "}", str(v))
    return tpl


SYSTEM = _res("pipeline/direction/prompts/system.md").strip()


@dataclass
class PageCtx:
    page_id: str
    img: np.ndarray
    reading: str
    us: UnitSet
    panels: list[dict] = field(default_factory=list)  # final, in reading order: id, src, bbox, poly
    desc: dict = field(default_factory=dict)  # panel id -> description fields
    units: list[dict] = field(default_factory=list)  # id, det, box (xyxy), kind, text, shout, panel
    story: str = ""
    must: list = field(default_factory=list)
    log: list = field(default_factory=list)

    def unit_boxes(self):
        return [(u["id"], u["det"], u["box"]) for u in self.units]


def candidate_panels(img, reading: str) -> list[dict]:
    det = detect_panels(img)
    ordered = [det[i] for i in order_panels([p.bbox for p in det], reading)]
    return [dict(id=f"P{i + 1}", bbox=p.bbox, poly=p.poly, score=p.score, source=p.source) for i, p in enumerate(ordered)]


def _finalize_panels(img, panels: list[dict], reading: str) -> list[dict]:
    """Order panels and rename ids to P1..Pn (the old id is kept in `src`)."""
    o = order_panels([p["bbox"] for p in panels], reading)
    out = []
    for k, i in enumerate(o):
        p = dict(panels[i])
        p["src"] = p.get("src", p["id"])
        p["id"] = f"P{k + 1}"
        out.append(p)
    return out


def _prompt_lists(panels, units):
    pl = "; ".join(f"{p['id']} {[round(v, 3) for v in p['bbox']]} ({p.get('source', '')})" for p in panels)
    ul = "; ".join(f"{u['id']} {u['det']} {[round(v, 2) for v in u['box']]} in {u.get('panel', '?')}" for u in units)
    return pl, ul


def init_ctx(img, page_id: str, reading: str = "rtl", us: UnitSet | None = None) -> PageCtx:
    us = us or analyze_units(img)
    ctx = PageCtx(page_id, img, reading, us)
    ctx.panels = candidate_panels(img, reading)
    asg = assign_units(us, ctx.panels)
    ctx.units = [dict(id=u.id, det=u.kind, box=u.box, kind=DET_TO_KIND[u.kind], text="", shout=False, panel=asg.get(u.id, "")) for u in us.units]
    return ctx


# ------------------------------------------------------------------ call A
def observe(ctx: PageCtx, provider, work: Path) -> dict:
    paths = write_inputs(ctx.img, ctx.panels, ctx.unit_boxes(), work, "A")
    pl, ul = _prompt_lists(ctx.panels, ctx.units)
    images = [paths["clean"], paths["overlay"]] + list(paths["crops"].values())
    prompt = fill(load_prompt("observe"), reading=ctx.reading, panel_list=pl, unit_list=ul)
    obs = provider.complete(prompt, system=SYSTEM, images=images, schema=load_schema("observe"), tag=f"observe:{ctx.page_id}")
    return obs


def apply_observation(ctx: PageCtx, obs: dict) -> None:
    cands = ctx.panels
    fixed, log = apply_panel_fixes(ctx.img, cands, obs.get("panel_fixes", []))
    ctx.log += log
    ctx.panels = _finalize_panels(ctx.img, fixed or cands, ctx.reading)
    src2id = {p["src"]: p["id"] for p in ctx.panels}
    # candidate ids that were merged away map to their group head
    for f in obs.get("panel_fixes", []):
        if f.get("op") == "merge":
            for i in f.get("ids", [])[1:]:
                src2id.setdefault(i, src2id.get(f["ids"][0], ""))
    ctx.desc = {}
    for d in obs.get("panels", []):
        pid = src2id.get(d["id"])
        if pid:
            ctx.desc[pid] = {k: v for k, v in d.items() if k != "id"}
    hints = {}
    by = {u["id"]: u for u in ctx.units}
    for lu in obs.get("units", []):
        u = by.get(lu["id"])
        if not u:
            continue
        u.update(kind=lu["kind"], text=lu.get("text", ""), shout=bool(lu.get("shout")))
        if lu.get("panel_id") in src2id:
            hints[u["id"]] = src2id[lu["panel_id"]]
    n = 0
    for au in obs.get("add_units", []):
        r = au.get("approx_rect") or []
        if len(r) != 4 or au.get("kind") not in FX_KINDS:
            continue
        box = [max(0.0, r[0]), max(0.0, r[1]), min(1.0, r[0] + r[2]), min(1.0, r[1] + r[3])]
        if box[2] - box[0] < 0.01 or box[3] - box[1] < 0.01:
            continue
        if any(_box_overlap(box, u["box"]) >= 0.5 for u in ctx.units):  # already a candidate
            continue
        n += 1
        uid = f"A{n}"
        ctx.units.append(dict(id=uid, det="added", box=box, kind=au["kind"], text="", shout=False, panel=""))
        if au.get("panel_id") in src2id:
            hints[uid] = src2id[au["panel_id"]]
    asg = assign_units(ctx.us, ctx.panels, hints)
    for u in ctx.units:
        if u["id"] in asg:
            u["panel"] = asg[u["id"]]
        elif u["id"] in hints:
            u["panel"] = hints[u["id"]]
        else:  # an LLM-added unit without a usable panel: the panel with the largest overlap of its box
            u["panel"] = max(ctx.panels, key=lambda p: _box_overlap(u["box"], [p["bbox"][0], p["bbox"][1], p["bbox"][0] + p["bbox"][2], p["bbox"][1] + p["bbox"][3]]))["id"]
    ctx.story = obs.get("page_story", "")
    ctx.must = [m for m in obs.get("must", []) if m.get("item") and m.get("how")]


def _box_overlap(a, b) -> float:
    iw, ih = max(0.0, min(a[2], b[2]) - max(a[0], b[0])), max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    s = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return iw * ih / s if s > 0 else 0.0


# ------------------------------------------------------------------ reading order
def unit_order(ctx: PageCtx, override: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """panel id -> ids of its dialogue/narration units in reading order: bands first, replaced by the LLM's order when that is a valid permutation."""
    res = {}
    for p in ctx.panels:
        mine = [u for u in ctx.units if u["panel"] == p["id"] and u["kind"] in TEXT_KINDS]
        ids = [mine[i]["id"] for i in band_order([u["box"] for u in mine], ctx.reading)]
        if override and p["id"] in override and sorted(override[p["id"]]) == sorted(ids):
            ids = list(override[p["id"]])
        res[p["id"]] = ids
    return res


def tiebreak(ctx: PageCtx, provider, work: Path) -> dict[str, list[str]]:
    """Show the geometric order of each panel with 2+ units to the LLM; it keeps or corrects it. Returns the panel orders it gave."""
    prop = {pid: ids for pid, ids in unit_order(ctx).items() if len(ids) >= 2}
    if not prop:
        return {}
    paths = write_inputs(ctx.img, ctx.panels, ctx.unit_boxes(), work, "O")
    prompt = fill(load_prompt("order"), reading=ctx.reading, proposal="; ".join(f"{pid}: {' '.join(ids)}" for pid, ids in prop.items()))
    out = provider.complete(prompt, system=SYSTEM, images=[paths["overlay"]], schema=load_schema("order"), tag=f"order:{ctx.page_id}")
    return {e["panel_id"]: e["unit_ids"] for e in out.get("panels", []) if e["panel_id"] in prop}


# ------------------------------------------------------------------ assemble
def rect_of(b):
    return [round(b[0], 5), round(b[1], 5), round(b[2] - b[0], 5), round(b[3] - b[1], 5)]


def assemble(ctx: PageCtx, direct: dict, override=None) -> dict:
    """Build the ugoku-direction/1 page from the observation (ctx) and the directing decisions. Pure function of its inputs."""
    pdec = {d["id"]: d for d in direct.get("panels", [])}
    udec = {d["id"]: d for d in direct.get("units", [])}
    uorder = unit_order(ctx, override)
    ubyid = {u["id"]: u for u in ctx.units}
    tmodel, total = compute_timing([
        dict(id=p["id"], lines=[dict(id=i, text=ubyid[i]["text"]) for i in uorder[p["id"]]], fx=[dict(id=u["id"]) for u in ctx.units if u["panel"] == p["id"] and u["kind"] in FX_KINDS])
        for p in ctx.panels
    ])
    pid2final = {p["id"]: f"{ctx.page_id}-p{k + 1}" for k, p in enumerate(ctx.panels)}
    panels, bubbles, fx = [], [], []
    for k, p in enumerate(ctx.panels):
        d, desc = pdec.get(p["id"], {}), ctx.desc.get(p["id"], {})
        typ = d.get("type", "static")
        q = dict(id=pid2final[p["id"]], order=k + 1, rect=[round(v, 5) for v in p["bbox"]], type=typ, role=d.get("role", "hold"), content=desc.get("content", ""),
                 reason=d.get("reason", "") or ("no decision" if not d else ""), timing_s=list(tmodel[p["id"]]))
        if p.get("poly") and p.get("source") == "classical" and len(p["poly"]) != 4:
            q["poly"] = p["poly"]
        if typ == "h3_full":
            q.update(action=d.get("action", ""), magnitude=d.get("magnitude", "medium"), mode=d.get("mode", "fl"), emotion_source=d.get("emotion_source", ""), seed=default_seed(q["id"]))
        if desc.get("no_character"):
            q["no_character"] = True
        panels.append(q)
    n = 0
    for p in ctx.panels:
        for uid in uorder[p["id"]]:
            u = ubyid[uid]
            n += 1
            anim = "shake" if u["shout"] else udec.get(uid, {}).get("anim", "pop")
            if anim == "none":
                anim = "pop"
            bubbles.append(dict(id=f"{ctx.page_id}-b{n}", unit=uid, panel=pid2final[p["id"]], rect=rect_of(u["box"]), text=u["text"], order=n, t_in=tmodel[uid], anim=anim))
    m = 0
    for p in ctx.panels:
        for u in ctx.units:
            if u["panel"] == p["id"] and u["kind"] in FX_KINDS:
                m += 1
                pr = udec.get(u["id"], {}).get("preset", "pop")
                if pr not in PRESETS:
                    pr = "pop"
                fx.append(dict(id=f"{ctx.page_id}-f{m}", unit=u["id"], panel=pid2final[p["id"]], rect=rect_of(u["box"]), text=u["text"], kind=u["kind"], preset=pr, t_in=tmodel[u["id"]]))
    h, w = ctx.img.shape[:2]
    return dict(page=ctx.page_id, image=f"{ctx.page_id}.png", w=w, h=h, story=ctx.story, total_s=total, must=ctx.must, panels=panels, bubbles=bubbles, fx=fx)


def _kinds(ctx):
    return {u["id"]: u["kind"] for u in ctx.units}


def validate_ctx(ctx: PageCtx, pg: dict) -> list[Issue]:
    return validate_page(pg, _kinds(ctx), sfx_detected=sum(1 for u in ctx.units if u["det"] == "sfx"))


# ------------------------------------------------------------------ call B / C
def _obs_json(ctx: PageCtx) -> str:
    uo = unit_order(ctx)
    order = {i: k for ids in uo.values() for k, i in enumerate(ids)}
    pan = [dict(id=p["id"], **ctx.desc.get(p["id"], {})) for p in ctx.panels]
    uni = [dict(id=u["id"], kind=u["kind"], text=u["text"], panel=u["panel"], shout=u["shout"], reading_index_in_panel=order.get(u["id"])) for u in ctx.units if u["kind"] != "noise"]
    return json.dumps(dict(story=ctx.story, panels=pan, units=uni), ensure_ascii=False)


def direct(ctx: PageCtx, provider, work: Path, feedback: str = "", prev: dict | None = None) -> dict:
    paths = write_inputs(ctx.img, ctx.panels, ctx.unit_boxes(), work, "B")
    images = [paths["clean"], paths["overlay"]] + list(paths["crops"].values())
    prompt = fill(load_prompt("direct"), observation=_obs_json(ctx))
    if feedback:
        prompt += "\n\nYour previous answer:\n" + json.dumps(prev, ensure_ascii=False) + "\n\nProblems to fix (return the complete corrected answer):\n" + feedback
    return provider.complete(prompt, system=SYSTEM, images=images, schema=load_schema("direct"), tag=f"direct:{ctx.page_id}" + (":fix" if feedback else ""))


def _direction_json(ctx: PageCtx, dec: dict) -> str:
    return json.dumps(dict(panels=dec.get("panels", []), units=[dict(d, kind=next((u["kind"] for u in ctx.units if u["id"] == d["id"]), "")) for d in dec.get("units", [])]), ensure_ascii=False)


def critic(ctx: PageCtx, provider, work: Path, dec: dict, warnings: list[Issue]) -> list[dict]:
    paths = write_inputs(ctx.img, ctx.panels, ctx.unit_boxes(), work, "C")
    images = [paths["clean"], paths["overlay"]] + list(paths["crops"].values())
    d = _direction_json(ctx, dec) + "\n\nObservation:\n" + _obs_json(ctx)
    if warnings:
        d += "\n\nValidator warnings to address:\n" + "\n".join(str(w) for w in warnings)
    out = provider.complete(fill(load_prompt("critic"), direction=d), system=SYSTEM, images=images, schema=load_schema("critic"), tag=f"critic:{ctx.page_id}")
    return out.get("issues", [])


def apply_patches(ctx: PageCtx, dec: dict, issues: list[dict]) -> int:
    """Apply critic fix patches to the decisions / observation in place. Returns the number of panels changed."""
    changed = set()
    pby = {d["id"]: d for d in dec["panels"]}
    uby = {d["id"]: d for d in dec["units"]}
    ukind = {u["id"]: u for u in ctx.units}
    for it in issues:
        t, fx = it["target_id"], it.get("fix_patch", {})
        if t in pby:
            for k in ("type", "role", "magnitude", "mode"):
                if fx.get(k) not in (None, "none", ""):
                    if pby[t].get(k) != fx[k]:
                        changed.add(t)
                    pby[t][k] = fx[k]
            if fx.get("action"):
                pby[t]["action"] = fx["action"]
                changed.add(t)
            if pby[t]["type"] == "static":
                pby[t].update(action="", magnitude="none", mode="none")
                pby[t]["reason"] = pby[t].get("reason") or it.get("explanation", "static")
            elif not pby[t].get("action"):
                pby[t]["action"] = pby[t].get("action", "")
        elif t in uby:
            if fx.get("kind") not in (None, "none", "") and t in ukind:
                ukind[t]["kind"] = fx["kind"]
            if fx.get("anim") not in (None, "none", ""):
                uby[t]["anim"] = fx["anim"]
            if fx.get("preset") not in (None, "none", ""):
                uby[t]["preset"] = fx["preset"]
            if fx.get("panel_id") in {p["id"] for p in ctx.panels} and t in ukind:
                ukind[t]["panel"] = fx["panel_id"]
    return len(changed)


def _complete_units(ctx: PageCtx, dec: dict) -> None:
    """Make sure each non-noise unit has a decision entry."""
    have = {d["id"] for d in dec["units"]}
    for u in ctx.units:
        if u["kind"] != "noise" and u["id"] not in have:
            dec["units"].append(dict(id=u["id"], anim="pop" if u["kind"] in TEXT_KINDS else "none", preset="none" if u["kind"] in TEXT_KINDS else "pop"))


def _targets(ctx: PageCtx, pg: dict, iss: list[Issue]) -> tuple[set, set]:
    """(panel ids, unit ids) in the observation's namespace that the issues point at."""
    fin2 = {f"{ctx.page_id}-p{k + 1}": p["id"] for k, p in enumerate(ctx.panels)}
    unit_of = {x["id"]: x.get("unit") for x in pg["bubbles"] + pg["fx"]}
    pans, units = set(), set()
    for i in iss:
        if i.target in fin2:
            pans.add(fin2[i.target])
        elif unit_of.get(i.target):
            units.add(unit_of[i.target])
        elif i.target.startswith("U") or i.target.startswith("A"):
            units.add(i.target)
    return pans, units


def _degrade(ctx: PageCtx, dec: dict, pg: dict, iss: list[Issue], report: dict) -> None:
    """Panels with errors become static; units with errors fall back to a plain entrance."""
    pans, units = _targets(ctx, pg, iss)
    for d in dec["panels"]:
        if d["id"] in pans and d["type"] == "h3_full":
            d.update(type="static", action="", magnitude="none", mode="none", reason="degraded after validation errors")
            report["degraded"].append(d["id"])
    for d in dec["units"]:
        if d["id"] in units:
            d.update(anim="pop" if d["anim"] != "none" else "none", preset="pop" if d["preset"] != "none" else "none")
            report["degraded"].append(d["id"])
    if not pans and not units:  # errors that point at the page itself (timing, order): nothing to degrade, they stay in the report
        report["degraded"].append(pg["page"])


def direct_page(img, page_id: str, provider, work: Path, reading: str = "rtl", us: UnitSet | None = None, max_repair: int = 3, max_critic: int = 2) -> tuple[dict, dict]:
    """Full workflow for one page. Returns (page dict of ugoku-direction/1, report)."""
    work.mkdir(parents=True, exist_ok=True)
    report = dict(page=page_id, repairs=0, critic_rounds=0, critic_changes=[], degraded=[], issues=[], redirect=False)
    ctx = init_ctx(img, page_id, reading, us)
    obs = observe(ctx, provider, work)
    apply_observation(ctx, obs)
    report["panel_log"] = ctx.log
    dec = direct(ctx, provider, work)
    _complete_units(ctx, dec)
    cons = tiebreak(ctx, provider, work)
    report["order_overrides"] = sum(1 for pid, ids in cons.items() if ids != unit_order(ctx)[pid])
    pg = assemble(ctx, dec, cons)
    iss = validate_ctx(ctx, pg)
    attempt = 0
    while errors(iss) and attempt < max_repair:
        attempt += 1
        report["repairs"] = attempt
        fb = "\n".join(str(i) for i in errors(iss))
        new = direct(ctx, provider, work, fb, dec)
        badp, badu = _targets(ctx, pg, errors(iss))
        dec["panels"] = [next((n for n in new["panels"] if n["id"] == d["id"]), d) if d["id"] in badp else d for d in dec["panels"]]
        dec["units"] = [next((n for n in new["units"] if n["id"] == d["id"]), d) if d["id"] in badu else d for d in dec["units"]]
        _complete_units(ctx, dec)
        pg = assemble(ctx, dec, cons)
        iss = validate_ctx(ctx, pg)
    if errors(iss):
        _degrade(ctx, dec, pg, errors(iss), report)
        pg = assemble(ctx, dec, cons)
        iss = validate_ctx(ctx, pg)
    for rnd in range(max_critic):
        found = critic(ctx, provider, work, dec, [i for i in iss if i.level == "warn"])
        report["critic_rounds"] = rnd + 1
        if not found:
            break
        n = apply_patches(ctx, dec, found)
        report["critic_changes"].append(dict(issues=len(found), panels_changed=n, rules=[f["rule"][:40] for f in found]))
        if n > 0.3 * len(ctx.panels) and not report["redirect"]:
            report["redirect"] = True
            dec = direct(ctx, provider, work, "A reviewer found these problems; avoid them:\n" + "\n".join(f"{f['target_id']}: {f['explanation']}" for f in found), dec)
            _complete_units(ctx, dec)
        pg = assemble(ctx, dec, cons)
        iss = validate_ctx(ctx, pg)
        if errors(iss):
            _degrade(ctx, dec, pg, errors(iss), report)
            pg = assemble(ctx, dec, cons)
            iss = validate_ctx(ctx, pg)
    report["issues"] = [str(i) for i in iss]
    report["valid"] = not errors(iss)
    report["valid_without_degrade"] = report["valid"] and not report["degraded"]
    return pg, report


def wrap_direction(pages: list[dict], work: str, reading: str, provider) -> dict:
    return dict(format=FORMAT, work=work, reading=reading, pages=pages,
                provenance=dict(llm=f"{provider.name}:{provider.model}", prompt_version=PROMPT_VERSION, detector_versions=dict(panels="classical-1", units="segment-1")))
