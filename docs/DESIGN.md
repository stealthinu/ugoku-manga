# Design

ugoku turns page images of a manga into a "moving manga": a gallery in which panels move (generated short clips), speech balloons and sound effects
appear in reading order, and everything plays in a browser. The whole path from a page image or a zip of pages to a playable result runs without human edits.
A web UI allows optional editing, but quality is always measured with editing off.

## Pipeline

```
page image -> panels (classical detector + LLM correction) -> text units (segmentation + box detector) -> reading order (code, LLM tie-break)
           -> direction (LLM workflow + validator) -> segment / inpaint (text-free base page, one layer per unit) -> stage (panel inputs for video)
           -> video backend (comfy_h3 | minimax_api | dummy) -> compose (gallery: base, layers, clips, timing) -> player / exports
```

Principle: **the model judges, code measures.** Detector boxes are shown to the LLM as numbered candidates (set-of-marks overlays); the LLM answers with ids and
never supplies final coordinates. Code snaps any proposed edge to the nearest gutter or contour.

### Panels (`pipeline/panels.py`)
1. Classical: gutter colour estimate (Otsu on the border histogram), flood fill from the outside, connected components, a hull-rectangularity filter and
   a recursive XY-cut that also cuts along drawn border lines. Slivers under 2% of the page are merged into a neighbour.
2. LLM correction (inside the observe call of the direction workflow): per candidate `confirm | merge | split | add | not_panel`; edges are snapped by code.
3. An ML panel detector is a plugin point; none is shipped. Models with non-redistributable or copyleft-for-weights licences are not used.

### Reading order (`pipeline/order.py`)
Deterministic. Panels: recursive XY-cut preferring row cuts, right to left inside a row for `rtl`; a 4-koma detector (one or two columns of four stacked panels).
Units are assigned to panels by overlap with the unit mask (a balloon that crosses panels goes to the panel holding its tail, or the first panel in order),
then ordered in bands (top to bottom) and right to left inside a band. Only ambiguous pairs go to the LLM, in one call; the answers become constraints
and a topological sort applies them.

### Direction (`pipeline/direction/`)
Three structured-output calls, all schema-constrained JSON:
- **Observe**: per panel a description (content, who, face size, expression, drawn motion), per unit its kind (dialogue, narration, sfx, manpu, screen, noise),
  transcription and panel, plus panel fixes and missed units.
- **Direct**: per panel `h3_full` or `static`, role, an English `action` whose first sentence is the main action (left and right as seen on screen),
  `magnitude` (medium, large) and `mode` (`fl` = starts and ends on the source drawing, `f` = one-way motion such as walking past or a kick); per unit an animation or effect preset.
- **Critic**: a checklist of the same rules, returning patches that are applied and validated again.

Code, not the LLM, computes unit order, entrance times (staggered by text length), panel timing, total duration, rects and default seeds.
A validator (`validate.py`) enforces what a schema cannot (ranges, containment, order, enum membership, every unit used once, action length, one-way verbs with `fl`).
On failure a repair call gets the exact error list (at most three attempts); then the offending panel degrades to `static` and the unit to a plain pop,
and the degradation is logged. Responses are cached on (image hash, detector version, prompt version, model).

Direction format: `ugoku-direction/1` (`schema/direction.schema.json`): pages with panels (`rect`, `type`, `role`, `action`, `magnitude`, `mode`, `timing_s`, `seed`),
bubbles (`unit`, `panel`, `rect`, `text`, `order`, `t_in`, `anim`) and fx (`kind`, `preset`, `t_in`).

Without any LLM, `heuristic.py` builds a direction from the detectors alone (largest panels animated with a generic action).

### Providers (`backends/llm/`)
`complete(prompt, images, schema) -> dict` with capability flags (vision, strict schema, tools). Implementations: `anthropic`, `openai_compat` (also local servers),
`gemini`, `replay` (recorded responses for CI), and `claude_cli`, which shells out to a local `claude` CLI that is logged in with a subscription
(API credentials are removed from the child environment, a login check runs first, and there is no fallback to another provider). Keys come from the environment only.

### Video backends (`backends/video/`)
`PanelJob{image, action, magnitude, mode, seed, frames=124, fps=24}`.
- `comfy_h3`: packs a stage directory and hands it to a runner. The job script (`gpu_scripts/comfy_h3_job.py`) is self-contained: Lanczos upscale onto a padded
  canvas (short side 768), a fixed 20-step graph, first/last-frame conditioning for `fl`, grayscale post-process back to the source size. It resumes from its manifest.
- `minimax_api`: hosted API, user-supplied key; never called by the development setup.
- `dummy`: a slow push-in, for CI and UI work.

### Runners (`backends/runner/`)
`local` runs the job script on this machine. `external_command` is template based: `sync_in`, `command`, optional `status` polling with a state regex, `sync_out`.
A submission record is written before and after submitting so a crashed caller resumes polling and never submits twice. The repository contains no host names;
a deployment keeps its commands in `~/.config/ugoku/config.toml` (see `examples/runner.external.toml`).

## Server and UI (`server/`, `web/ui/`)
FastAPI + SQLite. A `jobs` table with `(project, page, stage)` unique, status, attempts, lease and heartbeat; WAL mode.
CPU workers (ingest, direct, prep, compose) and one GPU worker (video) claim jobs; a worker that dies leaves an expired lease and the job is requeued (three attempts).
Stages are idempotent. Progress goes over server-sent events (`{stage, pct, eta_s, log_tail}`). Files are served with Range support so video seeking works.
Binding a non-loopback address needs `--public` because the UI has no login.

Flow: upload an image or a zip (natural order, reading direction, rights checkbox) -> automatic run -> optional editing (panel rects by drag, direction form,
mask preview, regenerate with a new seed) -> exports (gallery zip, single-file HTML per page, page mp4 composited in Python, per-panel clips).

## Evaluation (`eval/`)
Harness code only; private data locations come from a config file outside the repository, reports are written outside it, and committed summaries hold numbers and ids.
Metrics: panel IoU/recall/precision (Hungarian matching); unit recall per kind; Kendall tau and exact-match of the reading order; selection and mode agreement with a reference;
a text-leak QA on clips (text segmentation on every 12th frame, new text outside the removed-lettering mask, flagged above 0.4% of the panel);
motion metrics and a 1-5 clip score (motion strength, sharpness, flicker); an LLM visual judge on frame sheets.

Quality bar (all must pass to stop): panel IoU >= 0.85 and recall >= 0.95; bubble recall >= 0.90, SFX+manpu recall >= 0.75; order tau >= 0.90 and page exact >= 80%;
selection agreement >= 80%; direction valid without degrade on >= 95% of pages; QA flag rate within 5 points of the reference; mean score within 0.15 of the reference on the same
panels; share of clips scoring 4 or more within 10 points; judge mean within 0.2; synthetic golden tests (panel IoU >= 0.95, order 100%, unit recall >= 0.95).
GPU rounds use a fixed subset of 12 panels and cache clips on the spec hash, so only changed directions are regenerated.

## Samples (`samples/`, `tools/sample_gen/`)
Three original fictional works (action, romance-comedy, 4-koma) with exact ground truth (`truth.json`). Art comes from an Apache-2.0 text-to-image model run through the runner;
everything else (panel layout, borders, tone, balloons, lettering, sound effects, manpu) is drawn by code with OFL fonts, so the text is clean and the truth is exact.
Prompts contain no artist, franchise or character names (a test greps them). Sample pages are released as CC0-1.0; see `samples/LICENSE`.

## Hygiene
No file, history or asset of any earlier private project is included. CI runs a case-insensitive deny-list grep and a secret scanner; media files are allowed only under
`samples/`, `tests/fixtures/` and `docs/media/` and must be listed in `samples/MANIFEST.sha256`; files over 5 MB fail; every downloadable model in the registry needs a licence on the allowlist
(Apache-2.0, MIT, BSD, OFL) or is an optional user download with a NOTICE entry.
