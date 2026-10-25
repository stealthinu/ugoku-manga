# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-25

First public release (alpha).

### Added
- Fully automatic pipeline from page images to a browser-playable moving manga: classical panel detection with LLM correction, text and balloon detection,
  deterministic reading order, LLM direction workflow (observe, direct, critic) with a validator and repair loop, text removal and per-unit layers, staging, video, compose.
- `ugoku` CLI: `models list|fetch`, `run`, `direct`, `serve`.
- LLM providers: `anthropic`, `openai_compat`, `gemini`, `claude_cli`, `replay` (for tests), with a response cache. Default direction model: Claude Opus.
- Video backends: `comfy_h3` (MiniMax H3 through ComfyUI, via a `local` or `external_command` runner), `minimax_api` (hosted, untested against the live service), `dummy`.
- Heuristic direction without any LLM.
- Web UI (`ugoku serve`): FastAPI and SQLite job queue with leases, live progress over SSE, Range-capable file serving, panel and direction editing,
  clip regeneration, exports (gallery zip, single-file HTML, page mp4, clips).
- Player: base page, text layers and clips with timed entrances, deterministic seeking.
- Three original sample works under CC0-1.0 (`samples/`: 11 pages, 59 panels) with exact ground truth, and the generator in `tools/sample_gen/`.
- Evaluation harness (`eval/`): panel, unit and order metrics, clip score, text-leak QA, LLM judge, round reports; golden tests on the samples.
- Docker files (CPU image, ComfyUI GPU worker), README in English and Japanese with demo media, CONTRIBUTING, NOTICE.
- CI: ruff, pytest on Python 3.11-3.13, browser e2e, deny-list grep, repository policy check, gitleaks.

### Known limitations
- Clip quality on the samples is below the earlier private prototype (mean clip score 3.00 vs 3.30). See README "Limitations" and `eval/rounds/R05b.md`.
