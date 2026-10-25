"""Self-contained ComfyUI driver for whole-panel video generation. Runs wherever the GPU is (it needs no other part of this package).

Role: a rewrite of the reference batch driver of the earlier prototype, with the same fixed conditions (Lanczos upscale onto a padded canvas,
20 steps, 124 frames, first/last-frame conditioning, grayscale post-process). Only `spec.json` (seed, action, mode, magnitude) varies.

  python comfy_h3_job.py [--root DIR] [--only id,id] [--list] [--dry-run] [--check]

Layout under --root: in/ (panel images), spec.json, prep/, raw/ (model output), out/<id>.mp4 (post-processed, source panel size),
manifest.json, REPORT.md, comfy.log. Resume: panels with status ok in the manifest are skipped; a raw/ file without out/ is only post-processed.
ComfyUI is started by this script on a free port with --offline and only its own PID is stopped on exit.

Configuration comes from flags or environment (no machine paths in code):
  UGOKU_COMFY_DIR       ComfyUI checkout (contains main.py)                         [required unless --list/--dry-run]
  UGOKU_COMFY_EXTRA     extra_model_paths.yaml (optional)
  UGOKU_COMFY_DATA      output/temp directory for ComfyUI (default: <root>/comfy-data)
  UGOKU_GPU_NAME        substring the CUDA device name must contain (optional; unset = any device)
  UGOKU_COMFY_PORT      first port to try (default 8193)
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import socket
import subprocess
import sys
import time
import traceback

if "--dry-run" in sys.argv or "--check" in sys.argv or "--list" in sys.argv:
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # these modes never touch a GPU

import numpy as np
from PIL import Image

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261207
# short side 768, aspect ratio between 21:9 and 9:16
CANVASES = [(768, 768), (1024, 768), (1152, 768), (1344, 768), (768, 1024), (768, 1152), (768, 1344)]
FRAMES = 124
STEPS = 20
FPS = 24
MODE = "fl"
MODEL = dict(
    unet="minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    clip="qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    vae="minimax_h3_video_vae_fp16.safetensors",
    avae="minimax_h3_audio_vae_fp32.safetensors",
)  # the non-distilled model; the 8-step distilled variant is not used


def est_sec(W: int, H: int, frames: int = FRAMES, steps: int = STEPS) -> float:
    return 39 * (W * H / 200704) ** 1.3 * (steps / 8) * (frames / 73) ** 1.2 + 25


# ---- prompt -----------------------------------------------------------------------------------
STYLE = "Pure black and white manga ink line art with screentone, matching the style of <Picture 1>; the line art and faces keep their exact look."
NO_TEXT = (
    "The picture has no lettering: no letters, words, numbers, sound-effect characters or speech text appear at any moment of the video, "
    "and none are drawn anywhere."
)
BLANK = " Every blank white speech balloon stays empty and keeps its exact shape and position."
PHYS = "All motion follows natural physics, with weight and momentum. The sky, clouds and background buildings stay still unless the action names them."
PHYS_F = " People move only forward in the direction they face and never step backward; nothing moves in reverse."
INSTR1 = "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video."
INSTR2 = (
    "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
    "Picture 2 (from Shot 1) aligns with the {secs:.2f}-second mark of the target video."
)
MAG = {
    "large": "The motion is large, bold and immediately readable, using the whole body or the whole subject, and travelling a long way across the panel.",
    "medium": "The motion is clear and easy to see, moving the whole limb or upper body.",
}
KEEP = "Everything that is not part of this motion stays perfectly still. Panel borders and screentone keep their exact drawn shape and position."


def make_prompt(action: str, magnitude: str, frames: int = FRAMES, mode: str = "fl", blank: bool = False) -> str:
    secs = frames / FPS
    action = action.strip().replace(" No camera movement.", "")
    phys = PHYS + (PHYS_F if mode == "f" else "")
    keep = KEEP + (BLANK if blank else "")
    tail = " The shot ends exactly on <Picture 2>, the same drawing as the opening." if mode != "f" else ""
    body = (
        f"{STYLE} {NO_TEXT} The video opens exactly on <Picture 1>, keeping its composition, character design and line art. {action} "
        f"{MAG.get(magnitude, MAG['medium'])} {phys} {keep}{tail} The camera holds a static shot. One continuous {secs:.2f}-second shot with no cuts."
    )
    head = INSTR1 if mode == "f" else INSTR2.format(secs=secs)
    return head + f"\n\nintegrated_multimodal_description: [Shot 1] {body}\n\noverall_soundscape: Silence; no speech and no singing.\n\nnon_diegetic_music: N/A"


# ---- preprocess -------------------------------------------------------------------------------
def pick_canvas(w0: int, h0: int):
    best = None
    for W, H in CANVASES:
        s = min(W / w0, H / h0)
        waste = 1 - (w0 * s * h0 * s) / (W * H)
        if best is None or waste < best[0] - 1e-9:
            best = (waste, W, H, s)
    return best[1], best[2], best[3]


def prepare(root: str, src_path: str, key: str) -> dict:
    """Lanczos upscale onto a white padded canvas PNG in prep/. Returns {png, W, H, content(ox,oy,cw,ch), src(w0,h0)}."""
    im = Image.open(src_path).convert("RGB")
    w0, h0 = im.size
    W, H, s = pick_canvas(w0, h0)
    cw, ch = round(w0 * s), round(h0 * s)
    ox, oy = (W - cw) // 2, (H - ch) // 2
    png = f"{root}/prep/{key}.png"
    geo = dict(W=W, H=H, content=[ox, oy, cw, ch], src=[w0, h0], png=png)
    if not os.path.exists(png):
        os.makedirs(f"{root}/prep", exist_ok=True)
        cv = Image.new("RGB", (W, H), (255, 255, 255))
        cv.paste(im.resize((cw, ch), Image.LANCZOS), (ox, oy))
        cv.save(png)
    return geo


# ---- ComfyUI graph ----------------------------------------------------------------------------
def graph(img: str, prompt: str, W: int, H: int, frames: int, seed: int, steps: int, mode: str, prefix: str) -> dict:
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL["unet"], "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": MODEL["clip"], "type": "minimax", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": MODEL["vae"]}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": MODEL["avae"]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": img}},
    }
    i2v = {"clip": ["3", 0], "vae": ["4", 0], "prompt": prompt, "width": W, "height": H, "length": frames, "first_frame": ["6", 0]}
    if mode == "fl":
        i2v["last_frame"] = ["6", 0]  # the input is canvas-sized, so first and last frame are undistorted
    g["7"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": i2v}
    g.update({
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "10": {"class_type": "BasicScheduler", "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "11": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["7", 0]}},
        "12": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["8", 0], "guider": ["11", 0], "sampler": ["9", 0], "sigmas": ["10", 0], "latent_image": ["7", 1]}},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["4", 0]}},
        "14": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["12", 0], "vae": ["5", 0]}},
        "15": {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "audio": ["14", 0], "fps": float(FPS)}},
        "16": {"class_type": "SaveVideo", "inputs": {"video": ["15", 0], "filename_prefix": prefix, "format": "auto", "codec": "auto"}},
    })
    return g


def check_graph(g: dict) -> None:
    for nid, n in g.items():
        for k, v in n["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in g, f"node {nid}.{k} -> missing {v[0]}"


# ---- ComfyUI process / API --------------------------------------------------------------------
_proc = None
PORT = int(os.environ.get("UGOKU_COMFY_PORT", "8193"))
URL = ""


def free_port(start: int) -> int:
    for p in range(start, start + 40):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("no free port")


def start_comfy(root: str, cpu: bool = False) -> str:
    global _proc, PORT, URL
    import requests

    comfy = os.environ.get("UGOKU_COMFY_DIR")
    if not comfy:
        raise RuntimeError("UGOKU_COMFY_DIR is not set")
    PORT = free_port(PORT)
    URL = f"http://127.0.0.1:{PORT}"
    want = os.environ.get("UGOKU_GPU_NAME", "")
    dev_args: list[str] = []
    if cpu:
        dev_args = ["--cpu"]
    elif want and not os.environ.get("CUDA_VISIBLE_DEVICES"):
        import torch

        m = [i for i in range(torch.cuda.device_count()) if want in torch.cuda.get_device_name(i)]
        if not m:
            raise RuntimeError(f"no CUDA device with {want!r} in its name")
        dev_args = ["--cuda-device", str(m[0])]
    data = os.environ.get("UGOKU_COMFY_DATA") or f"{root}/comfy-data"
    args = [sys.executable, os.path.join(comfy, "main.py"), "--listen", "127.0.0.1", "--port", str(PORT), *dev_args, "--offline",
            "--output-directory", f"{data}/output", "--temp-directory", f"{data}/temp", "--preview-method", "none", "--cache-lru", "2", "--disable-auto-launch"]
    extra = os.environ.get("UGOKU_COMFY_EXTRA")
    if extra:
        args += ["--extra-model-paths-config", extra]
    if not cpu:
        args += ["--reserve-vram", "1.0", "--async-offload", "2", "--force-non-blocking", "--mmap-torch-files"]
    log = open(f"{root}/comfy.log", "ab")
    env = dict(os.environ)
    if cpu:
        env["CUDA_VISIBLE_DEVICES"] = ""
    _proc = subprocess.Popen(args, cwd=comfy, stdout=log, stderr=subprocess.STDOUT, env=env)
    t0 = time.time()
    while time.time() - t0 < 600:
        if _proc.poll() is not None:
            raise RuntimeError(f"ComfyUI exited rc={_proc.returncode} (see comfy.log)")
        try:
            st = requests.get(URL + "/system_stats", timeout=2).json()
            names = [d.get("name", "") for d in st.get("devices", [])]
            if not cpu and want and not any(want in n for n in names):
                stop_comfy()
                raise SystemExit(f"FATAL: ComfyUI device {names} does not match {want!r}")
            ver = st.get("system", {}).get("comfyui_version")
            print("comfyui up", round(time.time() - t0), "s port", PORT, "version", ver, "on", names, flush=True)
            return ver
        except requests.exceptions.RequestException:
            time.sleep(3)
    raise RuntimeError("ComfyUI start timeout")


def stop_comfy() -> None:
    global _proc
    if _proc and _proc.poll() is None:
        if os.name == "nt":
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(_proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        else:
            _proc.kill()
    _proc = None


atexit.register(stop_comfy)


def check_against_comfy(graphs: dict) -> list[str]:
    """Every class_type must exist in /object_info and every model name must be one of its choices."""
    import requests

    oi = requests.get(URL + "/object_info", timeout=120).json()
    bad = []
    for gid, g in graphs.items():
        for nid, n in g.items():
            ct = n["class_type"]
            if ct not in oi:
                bad.append(f"{gid}:{nid} class {ct} missing")
                continue
            req = {**oi[ct].get("input", {}).get("required", {}), **oi[ct].get("input", {}).get("optional", {})}
            for k, v in n["inputs"].items():
                if isinstance(v, list):
                    continue
                if k not in req:
                    bad.append(f"{gid}:{nid} {ct}.{k} is not an input")
                    continue
                spec = req[k][0]
                if isinstance(spec, list) and k != "image" and v not in spec:
                    bad.append(f"{gid}:{nid} {ct}.{k}={v!r} not among the choices ({spec[:4]}...)")
    return bad


def comfy_run(g: dict, img_path: str, name: str, timeout: int = 3000):
    import requests

    with open(img_path, "rb") as f:
        r = requests.post(URL + "/upload/image", files={"image": (name + ".png", f, "image/png")}, data={"overwrite": "true"})
    r.raise_for_status()
    g["6"]["inputs"]["image"] = r.json()["name"]
    r = requests.post(URL + "/prompt", json={"prompt": g, "client_id": "ugoku"})
    if r.status_code >= 400:
        raise RuntimeError("REJECT " + r.text[:800])
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while True:
        h = requests.get(f"{URL}/history/{pid}").json().get(pid)
        if h and h.get("status", {}).get("completed") is not None:
            break
        if time.time() - t0 > timeout:
            raise RuntimeError("timeout")
        if _proc and _proc.poll() is not None:
            raise RuntimeError("ComfyUI died")
        time.sleep(4)
    if h["status"].get("status_str") != "success":
        raise RuntimeError("FAILED " + json.dumps(h["status"])[:800])
    for o in h["outputs"].values():
        for v in o.get("images", []) + o.get("videos", []) + o.get("gifs", []):
            d = requests.get(URL + "/view", params={"filename": v["filename"], "subfolder": v.get("subfolder", ""), "type": v.get("type", "output")})
            return d.content, os.path.splitext(v["filename"])[1]
    raise RuntimeError("no video in the output")


# ---- post-process -----------------------------------------------------------------------------
def read_frames(path: str):
    import av

    with av.open(path) as c:
        return [f.to_ndarray(format="rgb24") for f in c.decode(video=0)]


def write_video(path: str, frames, fps: int = FPS) -> None:
    import av

    h, w = frames[0].shape[:2]
    with av.open(path, "w", format="mp4") as c:
        st = c.add_stream("libx264", rate=fps)
        st.width, st.height, st.pix_fmt = w, h, "yuv420p"
        st.options = {"crf": "12"}
        for fr in frames:
            for p in st.encode(av.VideoFrame.from_ndarray(fr, format="rgb24")):
                c.mux(p)
        for p in st.encode():
            c.mux(p)


def postprocess(raw_path: str, geo: dict, out_path: str) -> dict:
    """Crop the padding, Lanczos down to the source panel size (even), grayscale."""
    ox, oy, cw, ch = geo["content"]
    w0, h0 = geo["src"]
    ow, oh = w0 // 2 * 2, h0 // 2 * 2
    out = []
    for fr in read_frames(raw_path):
        im = Image.fromarray(fr).resize((ow, oh), Image.LANCZOS, box=(ox, oy, ox + cw, oy + ch)).convert("L").convert("RGB")
        out.append(np.asarray(im))
    tmp = out_path + ".tmp.mp4"
    write_video(tmp, out)
    os.replace(tmp, out_path)
    return dict(frames=len(out), size=[ow, oh], files=[out_path])


# ---- plan / run -------------------------------------------------------------------------------
def write_json(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write_report(root: str, man: dict, t_start: float) -> None:
    items = man["items"].values()
    n = lambda s: sum(1 for m in items if m["status"] == s)  # noqa: E731
    L = [f"# run report ({time.strftime('%Y-%m-%d %H:%M:%S')})", "",
         f"- elapsed {round((time.time() - t_start) / 60, 1)} min / ok {n('ok')} / failed {n('failed')} / pending {n('pending')} / total {len(man['items'])}",
         f"- dry_run={man['dry_run']}", "", "| id | status | sec | note |", "|---|---|---|---|"]
    for k, m in man["items"].items():
        L.append(f"| {k} | {m['status']} | {m.get('sec', '')} | {str(m.get('error') or '')[:120]} |")
    with open(f"{root}/REPORT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def build(root: str, ps: dict, cfg: dict):
    frames, steps = cfg.get("frames", FRAMES), cfg.get("steps", STEPS)
    geo = prepare(root, f"{root}/{ps['file']}", ps["id"])
    mode = ps.get("mode", MODE)
    prompt = make_prompt(ps["action"], ps.get("magnitude", "medium"), frames, mode, ps.get("blank_balloons", False))
    seed = ps.get("seed", SEED)
    g = graph("x.png", prompt, geo["W"], geo["H"], frames, seed, steps, mode, f"ugoku/{ps['id']}")
    check_graph(g)
    return geo, prompt, seed, g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=HERE)
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check", action="store_true", help="start ComfyUI on CPU and check every graph against /object_info (no GPU use)")
    a = ap.parse_args()
    root = a.root.replace("\\", "/")
    t_start = time.time()
    spec = json.load(open(f"{root}/spec.json", encoding="utf-8"))
    cfg = {k: v for k, v in spec.items() if k in ("frames", "steps")}
    only = a.only.split(",") if a.only else None
    items = [p for p in spec["panels"] if not only or p["id"] in only]
    if a.list:
        tot = 0.0
        for p in items:
            W, H, _ = pick_canvas(*Image.open(f"{root}/{p['file']}").size)
            e = est_sec(W, H)
            tot += e
            print(p["id"], f"{W}x{H}", round(e), "s")
        print(len(items), "items, est", round(tot / 3600, 2), "h")
        return
    for d in ("prep", "raw", "out", "dry_out"):
        os.makedirs(f"{root}/{d}", exist_ok=True)
    if a.check:
        graphs = {p["id"]: build(root, p, cfg)[3] for p in items}
        ver = start_comfy(root, cpu=True)
        try:
            bad = check_against_comfy(graphs)
        finally:
            stop_comfy()
        print("comfyui_version", ver, "graphs", len(graphs), "problems", len(bad))
        for b in bad:
            print("  BAD", b)
        write_json(f"{root}/check_result.json", dict(version=ver, graphs=len(graphs), problems=bad))
        sys.exit(1 if bad else 0)
    sub = "dry_out" if a.dry_run else "out"
    mpath = f"{root}/{'manifest_dry.json' if a.dry_run else 'manifest.json'}"
    man = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else {"items": {}}
    man.update(dry_run=a.dry_run, steps=cfg.get("steps", STEPS), frames=cfg.get("frames", FRAMES))
    for p in items:
        man["items"].setdefault(p["id"], dict(status="pending", panel=p["id"]))
    write_json(mpath, man)
    if not a.dry_run and items:
        start_comfy(root)
    try:
        for p in items:
            m = man["items"][p["id"]]
            outp = f"{root}/{sub}/{p['id']}.mp4"
            if m["status"] == "ok" and os.path.exists(outp):
                print(p["id"], "skip", flush=True)
                continue
            t0 = time.time()
            rawp = f"{root}/raw/{p['id']}.mp4"
            try:
                geo, prompt, seed, g = build(root, p, cfg)
                m.update(geo=geo, prompt=prompt, seed=seed, magnitude=p.get("magnitude"), mode=p.get("mode", MODE))
                if a.dry_run:
                    write_json(f"{root}/{sub}/{p['id']}.graph.json", g)
                    cv = np.asarray(Image.open(geo["png"]).convert("RGB"))
                    rawp = rawp.replace(".mp4", "_dry.mp4")
                    write_video(rawp, [cv] * 9)
                elif os.path.exists(rawp) and os.path.getsize(rawp) > 10000:
                    print(p["id"], "raw exists: post-process only", flush=True)
                else:
                    data, _ = comfy_run(g, geo["png"], p["id"])
                    with open(rawp + ".part", "wb") as f:
                        f.write(data)
                    os.replace(rawp + ".part", rawp)
                pp = postprocess(rawp, geo, outp)
                m.update(raw=rawp, files=pp["files"], out_size=pp["size"], out_frames=pp["frames"], status="ok", sec=round(time.time() - t0, 1))
                m.pop("error", None)
                print(p["id"], "ok", m["sec"], "s", flush=True)
            except Exception as e:
                m["status"] = "failed"
                m["error"] = f"{type(e).__name__}: {e}"[:600]
                m["sec"] = round(time.time() - t0, 1)
                print(p["id"], "FAILED", m["error"], flush=True)
                traceback.print_exc()
                if _proc is not None and _proc.poll() is not None:  # ComfyUI died: restart once
                    start_comfy(root)
            write_json(mpath, man)
            write_report(root, man, t_start)
    finally:
        stop_comfy()
        write_json(mpath, man)
        write_report(root, man, t_start)
    nok = sum(1 for m in man["items"].values() if m["status"] == "ok")
    print("done", nok, "ok /", len(man["items"]), flush=True)
    sys.exit(0 if all(m["status"] == "ok" for m in man["items"].values()) else 1)


if __name__ == "__main__":
    main()
