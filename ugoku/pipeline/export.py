"""Exports of a finished project: a single-file HTML per page, and a page mp4 composited in Python (no browser needed)."""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np

FPS = 24


# ------------------------------------------------------------------ single-file HTML
def _data_uri(p: Path) -> str:
    mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return f"data:{mt};base64," + base64.b64encode(p.read_bytes()).decode()


def page_html(out: Path, page_id: str) -> str:
    """One self-contained HTML file: the player with this page's data and every asset inlined as data URIs (videos too, so it can be large)."""
    d = json.loads((out / "data.json").read_text(encoding="utf-8"))
    pg = next(p for p in d["pages"] if p["id"] == page_id)
    pg = json.loads(json.dumps(pg))
    pg["image"] = _data_uri(out / pg["image"])
    pg.pop("thumb", None)
    for L in pg["layers"]:
        L["src"] = _data_uri(out / L["src"])
    for p in pg["panels"]:
        if p.get("mp4"):
            p["mp4"] = _data_uri(out / p["mp4"])
            p["webm"] = None
    data = dict(title=d.get("title", ""), works=d.get("works", []), pages=[pg])
    html = (out / "page.html").read_text(encoding="utf-8")
    css = (out / "style.css").read_text(encoding="utf-8")
    js = (out / "page.js").read_text(encoding="utf-8")
    shim = ("const __DATA=" + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + ";"
            "const __F=window.fetch;window.fetch=(u,...a)=>String(u).endsWith('data.json')?Promise.resolve(new Response(JSON.stringify(__DATA))):__F(u,...a);"
            f"const __U=URLSearchParams;window.URLSearchParams=class extends __U{{constructor(){{super('p={page_id}')}}}};")
    html = re.sub(r'<link[^>]*style\.css[^>]*>', lambda m: f"<style>{css}</style>", html)
    body = js.replace("</script>", "<\\/script>")
    html = re.sub(r'<script[^>]*src="page\.js"[^>]*></script>', lambda m: "<script>" + shim + "\n" + body + "</script>", html)
    return html


# ------------------------------------------------------------------ page mp4
def _ease_pop(u: float) -> float:
    return 0.7 + 0.3 * (1 - (1 - u) ** 3) + (0.06 * np.sin(np.pi * u) if u < 1 else 0)


def _blend(canvas: np.ndarray, rgba: np.ndarray, x: int, y: int, alpha: float = 1.0) -> None:
    H, W = canvas.shape[:2]
    h, w = rgba.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sub = rgba[y0 - y:y1 - y, x0 - x:x1 - x]
    a = (sub[..., 3:4].astype(np.float32) / 255.0) * alpha if sub.shape[2] == 4 else np.full(sub.shape[:2] + (1,), alpha, np.float32)
    canvas[y0:y1, x0:x1] = (canvas[y0:y1, x0:x1] * (1 - a) + sub[..., :3] * a).astype(np.uint8)


def _frames(path: Path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    out = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(f)
    cap.release()
    return out


def _px(rect, W, H):
    return round(rect[0] * W), round(rect[1] * H), max(1, round(rect[2] * W)), max(1, round(rect[3] * H))


def render_page_mp4(out: Path, page_id: str, dst: Path, ffmpeg: str = "ffmpeg", fps: int = FPS, tail_s: float = 1.0) -> Path:
    """Composite one page over time (base, panel clips, text/effect layers with pop/fade/shake/slide entrances) and encode it with ffmpeg."""
    d = json.loads((out / "data.json").read_text(encoding="utf-8"))
    pg = next(p for p in d["pages"] if p["id"] == page_id)
    W, H = pg["w"] // 2 * 2, pg["h"] // 2 * 2
    base = cv2.resize(cv2.imread(str(out / pg["image"])), (W, H))
    vids = [(p, _frames(out / p["mp4"])) for p in pg["panels"] if p.get("mp4") and (out / p["mp4"]).exists()]
    layers = []
    for o in sorted(pg["layers"], key=lambda o: (o.get("order", 0), o["t_in"])):
        im = cv2.imread(str(out / o["src"]), cv2.IMREAD_UNCHANGED)
        if im is None:
            continue
        if im.ndim == 2:
            im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
        if im.shape[2] == 3:
            im = np.dstack([im, np.full(im.shape[:2], 255, np.uint8)])
        x, y, w, h = _px(o["rect"], W, H)
        layers.append((o, cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA), x, y))
    total = pg["total_s"] + tail_s
    n = int(total * fps)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(dst)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(n):
            t = i / fps
            cv = base.copy()
            for p, fr in vids:
                if t >= p.get("start", 0) and fr:
                    k = min(len(fr) - 1, int((t - p["start"]) * fps))
                    x, y, w, h = _px(p["rect"], W, H)
                    cv[y:y + h, x:x + w] = cv2.resize(fr[k], (w, h))[: max(0, min(h, H - y)), : max(0, min(w, W - x))]
            for o, im, x, y in layers:
                u = (t - o["t_in"]) / 0.3
                if u < 0:
                    continue
                u = min(u, 1.0)
                anim = o.get("anim") or o.get("preset") or "pop"
                if anim == "fade":
                    _blend(cv, im, x, y, u)
                elif anim == "slide":
                    _blend(cv, im, x + round((1 - u) * 0.08 * W), y, u)
                elif anim == "shake":
                    j = round(3 * np.sin(t * 60)) if u >= 1 and t - o["t_in"] < 0.9 else 0
                    _blend(cv, im, x + j, y, min(1, u * 2))
                else:  # pop and every effect preset: scale in around the centre
                    s = _ease_pop(u)
                    sh, sw = max(1, round(im.shape[0] * s)), max(1, round(im.shape[1] * s))
                    sm = cv2.resize(im, (sw, sh))
                    _blend(cv, sm, x + (im.shape[1] - sw) // 2, y + (im.shape[0] - sh) // 2, min(1, u * 2))
            proc.stdin.write(cv.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode:
        raise RuntimeError("ffmpeg failed")
    return dst
