# eval

Harness code only; no data lives in this repo. Private data paths come from `~/.config/ugoku/eval.toml`
(or the file named by `UGOKU_EVAL_CONFIG`):

```toml
pages = "..."          # directory of page images, <page-id>.png
direction_v5 = "..."   # reference direction files of the earlier prototype (one JSON per work)
spec_v4 = "..."        # reference stage spec (pixel panel rects)
gallery_v5 = "..."     # reference gallery output (data.json, pages/, layers/)
work_v5 = "..."        # reference hide/flat masks
metrics_v5 = "..."     # (optional) reference motion metrics per clip, for the score self-test
scores_v5 = "..."      # (optional) reference 1-5 scores per clip
models = "..."         # directory with ctd.onnx, bubble.onnx, lama-manga-dynamic.onnx
out = "..."            # reports are written here, outside the repo
```

- `python -m eval.convert_ref` converts the reference direction files into `ugoku-direction/1` (written to `out/`).
- `python -m eval.parity` runs the CPU stage on the private pages and compares it with the reference gallery (P1 gate).

- `python -m eval.panels_eval` classical panel detection vs the reference rects (mean IoU, recall, precision).
- `python -m eval.layout_eval` text-unit candidates and reading order vs the reference layers (detector only, no LLM).
- `python -m eval.run_direction --tag R1` runs the LLM direction workflow on the eval pages through the `claude_cli` provider
  (local `claude` CLI, subscription login, API keys stripped from the child environment; never an API key) with a response cache in `out/llm-cache`.
- `python -m eval.direction_eval R1` scores the generated direction against the reference (panels, units, order, h3 selection and mode agreement, validity).
- `python -m eval.score5` recomputes the clip motion metrics and the 1-5 score from the reference videos and checks the formula against the reference scores.

Committed summaries contain numbers and ids only.
