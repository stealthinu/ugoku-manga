# ugoku

[日本語](README.ja.md)

Fully automatic "moving manga": page images in, a playable moving manga out. Panels get short generated clips, speech balloons and sound effects
appear in reading order, and the result plays in a browser. A web UI is included for optional editing.

Version 0.1.0 (first public release, alpha). See `CHANGELOG.md`, `docs/DESIGN.md` for how it works, and `eval/rounds/` for measured quality.

| shonen-rooftop p01 | shojo-afterschool p03 | koma-morning p01 |
|---|---|---|
| ![shonen-rooftop p01](docs/media/shonen-rooftop-p01.gif) | ![shojo-afterschool p03](docs/media/shojo-afterschool-p03.gif) | ![koma-morning p01](docs/media/koma-morning-p01.gif) |

These were made from the CC0 sample works in `samples/` with no manual edits (direction by a vision LLM, clips by MiniMax H3 through ComfyUI).
They were picked as typical rather than best pages. Stills: `docs/media/*-p0?.png`. Media licence: `docs/media/README.md`.

## Install

Python 3.11 or newer and `ffmpeg` (with libx264 and libvpx-vp9) on PATH.

```
git clone <this repository> ugoku && cd ugoku
python -m venv .venv && . .venv/bin/activate
pip install -e ".[server]"           # the web UI needs the server extra; plain `pip install -e .` is enough for the CLI
ugoku models fetch ctd bubble        # text and bubble detectors, downloaded to ~/.cache/ugoku/models (see NOTICE.md for licences)
ugoku models list
```

The inpainting model has no public download: if `lama-manga-dynamic.onnx` is missing, a plain OpenCV inpaint is used (lower quality, fine for a try).
Settings live in `~/.config/ugoku/config.toml` (or `$UGOKU_CONFIG`); every key can also be set as `UGOKU_<KEY>` (for example `UGOKU_MODEL_DIR`).
A CPU-only Docker image is in `docker/cpu.Dockerfile`.

## Quick start (no GPU, no API key)

```
ugoku run samples/shonen-rooftop/pages/*.png --direction samples/shonen-rooftop/direction.json --out out/   # dummy video backend
python -m http.server -d out 8000    # open http://localhost:8000; this server has no Range support, so clip seeking is limited
```

With the `dummy` backend each animated panel gets a slow push-in instead of a generated clip, which is enough to check layout, timing and the player.
All three samples run in a few minutes on a laptop CPU.

To let a vision LLM write the direction instead of using the supplied file:

```
export ANTHROPIC_API_KEY=...         # or OPENAI_API_KEY / GEMINI_API_KEY, or --provider claude_cli for a logged-in local `claude` CLI
ugoku direct my-pages/*.png --provider anthropic --out my.direction.json
ugoku run my-pages/*.png --direction my.direction.json --out out/
```

## Web UI

```
ugoku serve --data ugoku-data            # http://localhost:8771
ugoku serve --host 0.0.0.0 --public      # exposes it on the network; there is no login, so only on a trusted network
```

| upload | editing |
|---|---|
| ![upload form](docs/media/webui-upload.png) | ![panel editor](docs/media/webui-edit.png) |

1. Upload one image or a zip of pages (natural order), choose the reading direction, the video backend and how the direction is made
   (detector only, a vision LLM, or an uploaded direction file), and confirm you have the right to process the pages.
2. Progress streams live per page and stage.
3. Afterwards, optionally: drag panel rects, edit each panel's action, mode and magnitude, regenerate a clip with a new seed.
4. Export a gallery zip, a single-file HTML per page, a page mp4, or the per-panel clips.

## Pipeline

```
page image -> panels (classical detector + LLM correction) -> text units (segmentation + box detector) -> reading order (code, LLM tie-break)
           -> direction (LLM workflow + validator) -> segment / inpaint (text-free base page, one layer per unit) -> stage (panel inputs for video)
           -> video backend (comfy_h3 | minimax_api | dummy) -> compose (gallery: base, layers, clips, timing) -> player / exports
```

The model judges, code measures: the LLM picks among numbered detector candidates and writes the per-panel action, while code computes coordinates, order,
timing and validation. Details in `docs/DESIGN.md`.

## Models and hardware

| part | needs |
|---|---|
| panels, units, order, segmentation, compose, player | CPU, the detector models (`ugoku models fetch`) |
| direction by a vision LLM (`ugoku direct`) | a provider: `anthropic`, `openai_compat`, `gemini` (API keys from the environment: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`), or `claude_cli` (a local `claude` CLI logged in with a subscription). Default model: Claude Opus; Sonnet is the cheaper option |
| video clips, `comfy_h3` | an NVIDIA GPU with about 24 GB (developed on an RTX 3090; roughly 10-15 minutes per animated panel), a ComfyUI checkout with the MiniMax H3 nodes and weights, and a runner (`local`, or `external_command` for a GPU on another machine or behind a queue; see `examples/runner.external.toml` and `docker/comfy-gpu.Dockerfile`) |
| video clips, `minimax_api` | your own MiniMax API key (`MINIMAX_API_KEY`); results differ from local runs because the service pre-processes the prompt. Pages are sent to the service |
| video clips, `dummy` | nothing (a slow push-in, for tests and layout checks) |
| `ffmpeg` | with libx264 and libvpx-vp9, on PATH |

No model weights are bundled. MiniMax H3 has its own licence terms (region and revenue clauses among them). They apply to you, not to this repository.
Read them before generating or publishing clips. The text segmentation model is GPL-3.0 upstream and is an optional user download (`NOTICE.md`).

## Limitations

- Clip quality is below the earlier private prototype it was measured against: on the 18 animated sample panels the mean 1-5 clip score is 3.00 (reference 3.30),
  and 22% of clips score 4 or more (reference 37.5%). Some clips show little visible motion or the wrong direction. See `eval/rounds/R05b.md`.
- Borderless or faded panels are often missed by the classical panel detector, and 4-koma reading order is not always right without the LLM.
- Balloons that cross panels are assigned by text overlap and an LLM hint, not by the tail.
- Tuned for Japanese manga read right to left; left-to-right works but is less tested.
- The `minimax_api` backend is implemented but has not been run against the live service.
- The web UI has no login and no multi-user support. Keep it on localhost or a trusted network.
- The manga inpainting model needs a manual ONNX export (no public download); the OpenCV fallback gives a lower-quality text-free base page.

## Input rights

Only process pages you own or are allowed to process. When a hosted LLM or video API is used, the page images are uploaded to that service.

## Development

```
pip install -e ".[dev]"
ruff check . && pytest -q                         # golden tests run when the detector models are installed
python -m playwright install chromium && pytest -q -m e2e tests/e2e
bash scripts/deny_grep.sh && python scripts/check_repo.py
```

See `CONTRIBUTING.md`. Evaluation against private reference data is described in `eval/README.md`; nothing from such data is stored in this repository.
Sample works (original fiction, CC0-1.0) live in `samples/`; `tools/sample_gen/` regenerates them.

## Licence

Apache-2.0 for the code (`LICENSE`). Samples: CC0-1.0 (`samples/LICENSE`). Demo media: `docs/media/README.md`. Third-party models and fonts: `NOTICE.md`.
