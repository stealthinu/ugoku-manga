"""Stage preparation for one page: cut balloons / SFX / manpu into layers, build the text-free base page and the video inputs.

Origin: the prototype's page preparation step.
Output per page (under `out/`): pages/<id>.png (base), layers/<id>-L<n>.png (RGBA), work/ masks, stage/in/<panel>.png (video inputs).
Panels are processed independently of the video: the base page has every cut element removed (inpainted),
so video models never see letters they could distort.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .inpaint import hard_to_fill, inpaint_page
from .segment import Page, cut_dark_components, match_by_rect, overlap

LIGHT_RING = 0.9
TEXT_ANIM = {"pop": "fade", "slide": "fade", "fade": "fade", "shake": "shake"}


def px_rect(r, W, H):
    return [max(0, round(r[0] * W)), max(0, round(r[1] * H)), min(W, round((r[0] + r[2]) * W)), min(H, round((r[1] + r[3]) * H))]


def stage_rect(p, W, H):
    """Panel rect in pixels with even width and height (video codecs need it)."""
    x0, y0, x1, y1 = px_rect(p["rect"], W, H)
    return [x0, y0, x1 - (x1 - x0) % 2, y1 - (y1 - y0) % 2]


def _center_in(b, r):
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return r[0] <= cx <= r[2] and r[1] <= cy <= r[3]


def prepare_page(img: np.ndarray, pg: dict, work: str = "") -> tuple[dict, dict, list[dict], dict]:
    """Return (page_entry, report, stage_specs, files). `files` maps relative path -> ndarray/bytes to write."""
    H, W = img.shape[:2]
    pid = pg["page"]
    rep = dict(page=pid, warn=[], baked=[], text_only=[], unassigned=[])
    pans = pg["panels"]
    files: dict[str, np.ndarray] = {}
    if any(p["type"] == "keep" for p in pans):
        rep["keep"] = True
        files[f"pages/{pid}.png"] = img
        entry = dict(id=pid, work=work, label=pid, image=f"pages/{pid}.png", w=W, h=H, total_s=pg.get("total_s", 6.5), panels=[], layers=[], overlays=[])
        return entry, rep, [], files
    P = Page(img)
    gray = P.gray
    prect = {p["id"]: (stage_rect(p, W, H) if p["type"] == "h3_full" else px_rect(p["rect"], W, H)) for p in pans}
    by_id = {p["id"]: p for p in pans}

    def panel_of(b):
        for p in sorted(pans, key=lambda p: (prect[p["id"]][2] - prect[p["id"]][0]) * (prect[p["id"]][3] - prect[p["id"]][1])):
            if _center_in(b, prect[p["id"]]):
                return p
        return max(pans, key=lambda p: overlap(b, prect[p["id"]]))

    bl = [(by_id[b["panel"]], b) for b in pg.get("bubbles", [])]
    sfx = [(by_id[f["panel"]], f) for f in pg.get("fx", []) if f["kind"] == "sfx"]
    res, free = match_by_rect(P.units, [px_rect(b["rect"], W, H) for _, b in bl], [px_rect(f["rect"], W, H) for _, f in sfx])
    # third pass: inside a panel, pair rect-less bubbles with leftover units in reading order (right to left, top to bottom)
    for p in pans:
        nb = [i for i, (q, b) in enumerate(bl) if q is p and not res[i]]
        fu = [j for j in free if panel_of(P.units[j]["box"]) is p]
        if nb and fu:
            def rk(r):
                return (-(r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
            nb.sort(key=lambda i: rk(px_rect(bl[i][1]["rect"], W, H)))
            fu.sort(key=lambda j: rk(P.units[j]["box"]))
            for i, j in zip(nb, fu):
                res[i].append(j)
                free.remove(j)
    layers: list[dict] = []
    hide = np.zeros((H, W), np.uint8)  # filled by inpainting
    flat = np.zeros((H, W), np.uint8)  # filled with the balloon's own white (text only is removed)

    def add_text_unit(units, p, meta):
        nonlocal hide, flat
        m = np.zeros((H, W), np.uint8)
        for j in units:
            m |= P.units[j]["mask"]
        if not m.any():
            return False
        hard, d, f = hard_to_fill(img, m, prect[p["id"]])
        if any(P.units[j].get("textonly") for j in units) and not hard:
            hide |= m  # balloon shape not found: it stays in the base, the text appears on it
            meta.update(mode="text", anim=TEXT_ANIM.get(meta.get("anim", "fade"), "fade"), mask=m)
            rep["text_only"].append(f"{meta['id']} shape-not-found")
            layers.append(meta)
            return True
        if hard:
            t = np.zeros((H, W), np.uint8)
            for j in units:
                x0, y0, x1, y1 = P.units[j]["box"]
                t[y0:y1, x0:x1] |= P.txt[y0:y1, x0:x1]
            t = cv2.dilate(t, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))) & m
            fl = cv2.dilate(t, np.ones((3, 3), np.uint8)) & m
            flat |= fl
            meta.update(mode="text", anim=TEXT_ANIM.get(meta.get("anim", "fade"), "fade"), mask=cv2.dilate(t, np.ones((3, 3), np.uint8)) & m)
            rep["text_only"].append(f"{meta['id']} d{d:.0f} flat{f:.2f}")
        else:
            hide |= m
            meta.update(mode="full", mask=m)
        layers.append(meta)
        return True

    for i, (p, b) in enumerate(bl):
        if not res[i]:
            if b.get("text", "").strip():
                rep["warn"].append(f"no unit for bubble {b['id']} (left baked in)")
            rep["baked"].append("b:" + b["id"])
            continue
        add_text_unit(res[i], p, dict(kind="bubble", id=b["id"], text=b.get("text", ""), order=b["order"], t_in=b["t_in"], anim=b["anim"], panel=p["id"]))
    for j in free:  # text the direction does not list: erase too, shown after the panel's last bubble
        p = panel_of(P.units[j]["box"])
        ts = [b["t_in"] for q, b in bl if q is p]
        t_in = round((max(ts) + 0.6) if ts else ((p.get("timing_s") or [0.4])[0] + 0.4), 2)
        if add_text_unit([j], p, dict(kind="bubble", id=f"extra-{j}", text="", order=90, t_in=t_in, anim="fade", panel=p["id"])):
            rep["unassigned"].append(P.units[j]["box"])
    groups = P.sfx_groups(hide | flat)
    for p in pans:
        for fx in [f for f in pg.get("fx", []) if f["panel"] == p["id"]]:
            r = px_rect(fx["rect"], W, H)
            label = fx.get("text", "")
            if fx["kind"] == "sfx":
                m = P.sfx_mask(r, groups)
                if m is None:  # not found by the text detector: darkest connected components in the rect
                    m = cut_dark_components(gray, r, pad=6)
                    if int(m.sum()) < 30:
                        rep["warn"].append(f"sfx not cut {fx['id']}")
                        rep["baked"].append("f:" + fx["id"])
                        continue
                    m = cv2.dilate(m, np.ones((3, 3), np.uint8))
                m &= 1 - flat
                hide |= m
                layers.append(dict(kind="sfx", id=fx["id"], text=label, order=50, t_in=fx["t_in"], preset=fx["preset"], mask=m, panel=p["id"], mode="full"))
                continue
            if fx.get("baked"):
                rep["baked"].append("f:" + fx["id"])
                continue
            if fx["kind"] == "screen":
                if fx["preset"] == "mail_slide":
                    m = np.zeros((H, W), np.uint8)
                    m[r[1] : r[3], r[0] : r[2]] = 1
                    hide |= m
                    layers.append(dict(kind="screen", id=fx["id"], text=label, order=99, t_in=fx["t_in"], preset="mail_slide", mask=m, panel=p["id"], clip=prect[p["id"]], opaque=True, mode="full"))
                else:
                    rep["baked"].append("f:" + fx["id"] + "(screen overlay)")
                continue
            # manpu: drips on a face stay in the video; others are cut like v4
            if fx["preset"] == "drip" and p["type"] == "h3_full":
                rep["baked"].append("f:" + fx["id"])
                continue
            m = cut_dark_components(gray, r, pad=6)
            if int(m.sum()) < 30:
                rep["baked"].append("f:" + fx["id"])
                continue
            pa = prect[p["id"]]
            ys_, xs_ = np.where(m > 0)
            if (xs_.max() - xs_.min()) * (ys_.max() - ys_.min()) > 0.12 * (pa[2] - pa[0]) * (pa[3] - pa[1]):
                rep["baked"].append("f:" + fx["id"] + "(large manpu left to the video)")
                continue
            m = cv2.dilate(m, np.ones((3, 3), np.uint8)) & (1 - flat)
            hide |= m
            layers.append(dict(kind=fx["kind"], id=fx["id"], text=label, order=50, t_in=fx["t_in"], preset=fx["preset"], mask=m, panel=p["id"], mode="full"))
    hide = cv2.dilate(hide, np.ones((3, 3), np.uint8)) & (1 - flat)
    # leftover text check: text pixels outside every mask
    left = P.txt & (1 - cv2.dilate(hide | flat, np.ones((7, 7), np.uint8)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(left, connectivity=8)
    big = []
    for i in range(1, n):
        if st[i, 4] < 120:
            continue
        # the detector also fires on dense line art and screentone; real lettering sits on a light ground, so a blob counts only when its surrounding ring is mostly white
        m = (lab == i).astype(np.uint8)
        ring = (cv2.dilate(m, np.ones((15, 15), np.uint8)) - cv2.dilate(m, np.ones((3, 3), np.uint8))) > 0
        if ring.any() and float((gray[ring] > 200).mean()) >= LIGHT_RING:
            big.append(list(map(int, st[i][:4])))
    if big:
        rep["warn"].append(f"possible leftover text: {len(big)} blobs {big[:6]}")
    base = img.copy()
    if flat.any():  # text-only layers: paint the balloon interior colour (median of the surrounding ring)
        for meta in layers:
            if meta.get("mode") != "text":
                continue
            fm = cv2.dilate(meta["mask"], np.ones((3, 3), np.uint8))
            ring = (cv2.dilate(fm, np.ones((7, 7), np.uint8)) - fm) > 0
            med = np.median(img[ring], axis=0) if ring.any() else np.array([255, 255, 255])
            base[fm > 0] = med.astype(np.uint8)
    if hide.any():
        base = inpaint_page(base, hide, [prect[p["id"]] for p in pans])
    files[f"pages/{pid}.png"] = base
    files[f"work/hide_{pid}.png"] = hide * 255
    files[f"work/flat_{pid}.png"] = flat * 255
    th = cv2.resize(base, (340, round(340 * H / W)), interpolation=cv2.INTER_AREA)
    files[f"thumbs/{pid}.jpg"] = th
    out = []
    layers = [lay for lay in layers if int((lay["mask"] > 0).sum()) >= 20]
    for i, lay in enumerate(layers):
        ys, xs = np.where(lay["mask"] > 0)
        pad = 3
        x0, y0, x1, y1 = max(0, xs.min() - pad), max(0, ys.min() - pad), min(W, xs.max() + 1 + pad), min(H, ys.max() + 1 + pad)
        if lay.get("opaque"):
            a = cv2.GaussianBlur(lay["mask"].astype(np.float32) * 255, (0, 0), 1.2)[y0:y1, x0:x1].astype(np.uint8)
        else:
            a = cv2.GaussianBlur(lay["mask"] * 255, (0, 0), 0.7)[y0:y1, x0:x1]
        fn = f"layers/{pid}-L{i}.png"
        files[fn] = np.dstack([img[y0:y1, x0:x1], a])
        d = dict(id=f"{pid}-L{i}", ref=lay["id"], kind=lay["kind"], text=lay["text"], order=lay["order"], t_in=lay["t_in"], src=fn,
                 rect=[x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H], panel=lay["panel"], mode=lay["mode"])
        for k in ("anim", "preset"):
            if k in lay:
                d[k] = lay[k]
        if "clip" in lay:
            c = lay["clip"]
            d["clip"] = [c[0] / W, c[1] / H, (c[2] - c[0]) / W, (c[3] - c[1]) / H]
        out.append(d)
    panels, stage = [], []
    for p in pans:
        if p["type"] != "h3_full":
            continue
        x0, y0, x1, y1 = prect[p["id"]]
        panels.append(dict(id=p["id"], rect=[x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H], start=p["timing_s"][0], action=p.get("action", "")[:160],
                           mp4=f"media/{p['id']}.mp4", webm=f"media/{p['id']}.webm", src_rect=[x0, y0, x1, y1], mode=p.get("mode", "fl")))
        fn = f"stage/in/{p['id']}.png"
        files[fn] = base[y0:y1, x0:x1]
        stage.append(dict(id=p["id"], file=fn.removeprefix("stage/"), page=pid, src_rect=[x0, y0, x1, y1], action=p["action"], magnitude=p.get("magnitude", "medium"),
                          mode=p.get("mode", "fl"), timing_s=p.get("timing_s"), type="h3_full", seed=p.get("seed", 0),
                          blank_balloons=any(lay["mode"] == "text" and lay["panel"] == p["id"] for lay in layers)))
    panels.sort(key=lambda q: -q["rect"][2] * q["rect"][3])
    for p in pans:
        if p["type"] == "static":
            panels.append(dict(id=p["id"], static=True, rect=p["rect"], reason=p.get("reason", "")[:100]))
    rep["n_layers"] = len(out)
    rep["stage"] = [s["id"] for s in stage]
    entry = dict(id=pid, work=work, label=pid, image=f"pages/{pid}.png", thumb=f"thumbs/{pid}.jpg", w=W, h=H, total_s=pg.get("total_s", 10),
                 panels=panels, layers=out, overlays=[])
    return entry, rep, stage, files


def write_files(root: Path, files: dict) -> None:
    for rel, arr in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(p), arr)


def write_spec(root: Path, stage: list[dict]) -> None:
    (root / "stage").mkdir(parents=True, exist_ok=True)
    (root / "stage" / "spec.json").write_text(json.dumps(dict(panels=stage), ensure_ascii=False, indent=1), encoding="utf-8")
