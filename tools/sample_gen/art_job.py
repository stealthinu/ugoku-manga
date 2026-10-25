"""Text-to-image driver for the sample art (Qwen-Image through ComfyUI). Runs wherever the GPU is, next to comfy_h3_job.py (it reuses its ComfyUI helpers).

  python art_job.py --root DIR [--check]

DIR/spec.json: {"steps": 20, "cfg": 2.5, "images": [{"id", "prompt", "negative", "w", "h", "seed"}]}; results go to DIR/out/<id>.png, DIR/manifest.json.
Resume: ids with a result file are skipped. Environment as for comfy_h3_job.py (UGOKU_COMFY_DIR, UGOKU_COMFY_EXTRA, UGOKU_COMFY_DATA, UGOKU_GPU_NAME).
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if "--check" in sys.argv:
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
import comfy_h3_job as ch  # noqa: E402

MODEL = dict(unet="qwen_image_fp8_e4m3fn.safetensors", clip="qwen_2.5_vl_7b_fp8_scaled.safetensors", vae="qwen_image_vae.safetensors")


def graph(prompt: str, negative: str, w: int, h: int, seed: int, steps: int, cfg: float, prefix: str) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": MODEL["clip"], "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": MODEL["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0], "seed": seed,
                                                    "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }


def run_prompt(g: dict, timeout: int = 1800):
    import requests

    r = requests.post(ch.URL + "/prompt", json={"prompt": g, "client_id": "ugoku"})
    if r.status_code >= 400:
        raise RuntimeError("REJECT " + r.text[:800])
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while True:
        h = requests.get(f"{ch.URL}/history/{pid}").json().get(pid)
        if h and h.get("status", {}).get("completed") is not None:
            break
        if time.time() - t0 > timeout:
            raise RuntimeError("timeout")
        time.sleep(2)
    if h["status"].get("status_str") != "success":
        raise RuntimeError("FAILED " + json.dumps(h["status"])[:800])
    for o in h["outputs"].values():
        for v in o.get("images", []):
            return requests.get(ch.URL + "/view", params={"filename": v["filename"], "subfolder": v.get("subfolder", ""), "type": v.get("type", "output")}).content
    raise RuntimeError("no image in the output")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=HERE)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    root = a.root.replace("\\", "/")
    spec = json.load(open(f"{root}/spec.json", encoding="utf-8"))
    steps, cfg = spec.get("steps", 20), spec.get("cfg", 2.5)
    items = spec["images"]
    graphs = {i["id"]: graph(i["prompt"], i.get("negative", ""), i["w"], i["h"], i["seed"], steps, cfg, f"sample/{i['id']}") for i in items}
    os.makedirs(f"{root}/out", exist_ok=True)
    if a.check:
        ver = ch.start_comfy(root, cpu=True)
        try:
            bad = ch.check_against_comfy({k: graphs[k] for k in list(graphs)[:1]})
        finally:
            ch.stop_comfy()
        print("comfyui_version", ver, "problems", len(bad))
        for b in bad:
            print("  BAD", b)
        sys.exit(1 if bad else 0)
    mpath = f"{root}/manifest.json"
    man = json.load(open(mpath)) if os.path.exists(mpath) else {"items": {}}
    todo = [i for i in items if not os.path.exists(f"{root}/out/{i['id']}.png")]
    if todo:
        ch.start_comfy(root)
    try:
        for i in todo:
            t0 = time.time()
            try:
                data = run_prompt(graphs[i["id"]])
                with open(f"{root}/out/{i['id']}.png.part", "wb") as f:
                    f.write(data)
                os.replace(f"{root}/out/{i['id']}.png.part", f"{root}/out/{i['id']}.png")
                man["items"][i["id"]] = dict(status="ok", sec=round(time.time() - t0, 1), seed=i["seed"])
            except Exception as e:  # noqa: BLE001
                man["items"][i["id"]] = dict(status="failed", error=f"{type(e).__name__}: {e}"[:500])
            print(i["id"], man["items"][i["id"]]["status"], round(time.time() - t0), "s", flush=True)
            ch.write_json(mpath, man)
    finally:
        ch.stop_comfy()
        ch.write_json(mpath, man)
    for i in items:
        if os.path.exists(f"{root}/out/{i['id']}.png"):
            man["items"].setdefault(i["id"], dict(status="ok"))
    ch.write_json(mpath, man)
    sys.exit(0 if all(man["items"].get(i["id"], {}).get("status") == "ok" for i in items) else 1)


if __name__ == "__main__":
    main()
